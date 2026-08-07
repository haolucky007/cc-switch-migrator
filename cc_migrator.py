"""
CC Switch Skills & MCP 迁移工具 - GUI 主程序

轻量级桌面工具，实现 Skills、MCP Servers、API Providers
从一台电脑一键迁移到另一台电脑。

使用方法:
    python cc_migrator.py

依赖:
    pip install customtkinter
"""

import os
import sys
import json
import sqlite3
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from datetime import datetime

try:
    import customtkinter as ctk
except ImportError:
    print("请先安装 customtkinter: pip install customtkinter")
    sys.exit(1)

from cc_migrator_core import (
    PathDetector,
    HealthChecker,
    BackupEngine,
    RestoreEngine,
)

# =============================================================================
#  全局配置 — 匹配 CC Switch 风格
# =============================================================================

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

COLORS = {
    'bg': '#1e1e1e',
    'bg_secondary': '#252526',
    'card': '#252526',
    'card_hover': '#2d2d2d',
    'sidebar': '#181818',
    'accent': '#1473e6',
    'accent_hover': '#0d5fb8',
    'accent_soft': '#1a3a5c',
    'text': '#cccccc',
    'text_dim': '#808080',
    'text_bright': '#e8e8e8',
    'success': '#4ec9b0',
    'warn': '#dcdcaa',
    'error': '#f44747',
    'info': '#569cd6',
    'border': '#3c3c3c',
}

FONT_TITLE = ('楷体', 18, 'bold')
FONT_SUBTITLE = ('楷体', 13)
FONT_BODY = ('楷体', 11)
FONT_SMALL = ('楷体', 9)
FONT_SECTION = ('楷体', 13, 'bold')
FONT_CARD_TITLE = ('楷体', 15, 'bold')
FONT_MONO = ('Consolas', 10)


def _configure_text_tags(textbox):
    """为 CTkTextbox 配置颜色标签"""
    try:
        textbox._textbox.tag_configure('success', foreground=COLORS['success'])
        textbox._textbox.tag_configure('warn', foreground=COLORS['warn'])
        textbox._textbox.tag_configure('error', foreground=COLORS['error'])
        textbox._textbox.tag_configure('info', foreground=COLORS['info'])
    except Exception:
        pass


# =============================================================================
#  主应用
# =============================================================================

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("CC Switch 迁移工具")
        self.geometry("960x640")
        self.minsize(820, 560)
        self.configure(fg_color=COLORS['bg'])

        # 左侧导航栏 — 匹配 CC Switch 侧边栏风格
        self.sidebar = ctk.CTkFrame(self, fg_color=COLORS['sidebar'], width=180, corner_radius=0)
        self.sidebar.pack(fill='y', side='left')
        self.sidebar.pack_propagate(False)

        # 侧边栏 Logo/标题
        logo_label = ctk.CTkLabel(
            self.sidebar, text="CC Switch",
            font=FONT_TITLE, text_color=COLORS['accent']
        )
        logo_label.pack(pady=(20, 5))

        version_label = ctk.CTkLabel(
            self.sidebar, text="迁移工具",
            font=FONT_SMALL, text_color=COLORS['text_dim']
        )
        version_label.pack(pady=(0, 20))

        # 分割线
        separator = ctk.CTkFrame(self.sidebar, fg_color=COLORS['border'], height=1, corner_radius=0)
        separator.pack(fill='x', padx=16, pady=(0, 10))

        # 导航按钮
        self.nav_buttons = {}
        nav_items = [
            ('home', '  主页'),
            ('backup', '  备份'),
            ('restore', '  恢复'),
            ('selective', '  选择性迁移'),
        ]
        for name, label in nav_items:
            btn = ctk.CTkButton(
                self.sidebar, text=label, font=FONT_BODY,
                fg_color='transparent', hover_color=COLORS['card_hover'],
                text_color=COLORS['text_dim'], corner_radius=4,
                height=34, anchor='w',
                command=lambda n=name: self.show_view(n)
            )
            btn.pack(fill='x', padx=8, pady=2)
            self.nav_buttons[name] = btn

        # 内容区域
        self.content = ctk.CTkFrame(self, fg_color=COLORS['bg'], corner_radius=0)
        self.content.pack(fill='both', expand=True)

        # 当前视图
        self.current_view = None
        self.views = {}

        # 初始化
        self.show_view('home')

    def show_view(self, name):
        """切换视图"""
        # 更新导航按钮颜色
        for n, btn in self.nav_buttons.items():
            if n == name:
                btn.configure(text_color=COLORS['accent'], fg_color=COLORS['accent_soft'])
            else:
                btn.configure(text_color=COLORS['text_dim'], fg_color='transparent')

        # 销毁当前视图
        if self.current_view:
            self.current_view.destroy()

        # 创建新视图
        if name == 'home':
            self.current_view = HomeView(self.content, self)
        elif name == 'backup':
            self.current_view = BackupView(self.content, self)
        elif name == 'restore':
            self.current_view = RestoreView(self.content, self)
        elif name == 'selective':
            self.current_view = SelectiveView(self.content, self)

        self.current_view.pack(fill='both', expand=True, padx=16, pady=12)


# =============================================================================
#  主页视图
# =============================================================================

class HomeView(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color=COLORS['bg'])
        self.app = app

        # 标题
        title = ctk.CTkLabel(self, text="CC Switch 迁移工具", font=FONT_TITLE, text_color=COLORS['accent'])
        title.pack(pady=(20, 3))

        subtitle = ctk.CTkLabel(self, text="一键迁移 Skills、MCP Servers 和 API 配置", font=FONT_SUBTITLE, text_color=COLORS['text_dim'])
        subtitle.pack(pady=(0, 20))

        # 三个模式卡片
        cards_frame = ctk.CTkFrame(self, fg_color='transparent')
        cards_frame.pack(fill='x', padx=20)

        cards = [
            ('backup', '备份', '在旧电脑上打包所有配置', '将 Skills、MCP、Providers\n打包为迁移包'),
            ('restore', '恢复', '在新电脑上还原配置', '从迁移包恢复，自动适配\n路径和创建符号链接'),
            ('selective', '选择性迁移', '自选要迁移的项目', '勾选需要的 Skills、MCPs\n和 Providers 进行迁移'),
        ]

        for i, (view, title_text, desc, detail) in enumerate(cards):
            card = self._create_card(cards_frame, title_text, desc, detail, view)
            card.grid(row=0, column=i, padx=6, pady=6, sticky='nsew')

        cards_frame.grid_columnconfigure((0, 1, 2), weight=1)

        # 底部状态
        self._show_status()

    def _create_card(self, parent, title, desc, detail, view_name):
        card = ctk.CTkFrame(parent, fg_color=COLORS['card'], corner_radius=6, border_width=1, border_color=COLORS['border'])

        inner = ctk.CTkFrame(card, fg_color='transparent')
        inner.pack(fill='both', expand=True, padx=16, pady=16)

        label_title = ctk.CTkLabel(inner, text=title, font=FONT_CARD_TITLE, text_color=COLORS['accent'])
        label_title.pack(pady=(6, 3))

        label_desc = ctk.CTkLabel(inner, text=desc, font=FONT_SMALL, text_color=COLORS['text_dim'])
        label_desc.pack(pady=(0, 8))

        label_detail = ctk.CTkLabel(inner, text=detail, font=FONT_SMALL, text_color=COLORS['text'], justify='left')
        label_detail.pack(pady=(0, 12))

        btn = ctk.CTkButton(
            inner, text=f"进入 {title}", font=FONT_BODY,
            fg_color=COLORS['accent'], hover_color=COLORS['accent_hover'],
            corner_radius=4, height=30,
            command=lambda: self.app.show_view(view_name)
        )
        btn.pack(fill='x', pady=(0, 4))

        return card

    def _show_status(self):
        """显示当前环境状态"""
        status_frame = ctk.CTkFrame(self, fg_color=COLORS['card'], corner_radius=6, border_width=1, border_color=COLORS['border'])
        status_frame.pack(fill='x', padx=20, pady=(8, 0))

        label = ctk.CTkLabel(status_frame, text="当前环境", font=FONT_SECTION, text_color=COLORS['text_dim'])
        label.pack(anchor='w', padx=14, pady=(8, 4))

        detector = PathDetector()
        tools = detector.detect_installed_tools()

        row = ctk.CTkFrame(status_frame, fg_color='transparent')
        row.pack(fill='x', padx=14, pady=(0, 8))

        for name, installed in tools.items():
            color = COLORS['success'] if installed else COLORS['error']
            icon = "✓" if installed else "✗"
            lbl = ctk.CTkLabel(row, text=f"{icon} {name}", font=FONT_SMALL, text_color=color)
            lbl.pack(side='left', padx=6)

        py_path = detector.detect_python()
        py_label = ctk.CTkLabel(status_frame, text=f"Python: {py_path or '未检测到'}", font=FONT_MONO, text_color=COLORS['text_dim'])
        py_label.pack(anchor='w', padx=14, pady=(0, 8))


# =============================================================================
#  备份视图
# =============================================================================

class BackupView(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color=COLORS['bg'])
        self.app = app
        self.engine = BackupEngine()
        self.health_checker = HealthChecker()

        # 标题
        title = ctk.CTkLabel(self, text="备份", font=FONT_TITLE, text_color=COLORS['accent'])
        title.pack(anchor='w', pady=(0, 8))

        # 健康检查区域
        health_frame = ctk.CTkFrame(self, fg_color=COLORS['card'], corner_radius=6, border_width=1, border_color=COLORS['border'])
        health_frame.pack(fill='x', pady=(0, 8))

        health_title = ctk.CTkLabel(health_frame, text="迁移前健康检查", font=FONT_SECTION, text_color=COLORS['text'])
        health_title.pack(anchor='w', padx=14, pady=(8, 6))

        self.health_text = ctk.CTkTextbox(health_frame, height=100, font=FONT_MONO, fg_color=COLORS['bg'], text_color=COLORS['text'], corner_radius=4)
        self.health_text.pack(fill='x', padx=14, pady=(0, 8))
        _configure_text_tags(self.health_text)

        # 运行健康检查
        self._run_health_check()

        # 进度区域
        self.progress_label = ctk.CTkLabel(self, text="就绪", font=FONT_SMALL, text_color=COLORS['text_dim'])
        self.progress_label.pack(anchor='w', pady=(4, 2))

        self.progress_bar = ctk.CTkProgressBar(self, height=6, corner_radius=3, progress_color=COLORS['accent'])
        self.progress_bar.pack(fill='x', pady=(0, 8))
        self.progress_bar.set(0)

        # 日志区域
        self.log_text = ctk.CTkTextbox(self, height=90, font=FONT_MONO, fg_color=COLORS['card'], text_color=COLORS['text'], corner_radius=4)
        self.log_text.pack(fill='both', expand=True, pady=(0, 8))
        _configure_text_tags(self.log_text)

        # 按钮区域
        btn_frame = ctk.CTkFrame(self, fg_color='transparent')
        btn_frame.pack(fill='x', pady=(4, 0))

        self.backup_btn = ctk.CTkButton(
            btn_frame, text="开始备份", font=FONT_BODY,
            fg_color=COLORS['accent'], hover_color=COLORS['accent_hover'],
            corner_radius=4, height=34,
            command=self._start_backup
        )
        self.backup_btn.pack(side='right', padx=(8, 0))

        self.path_label = ctk.CTkLabel(btn_frame, text="", font=FONT_SMALL, text_color=COLORS['text_dim'])
        self.path_label.pack(side='left')

    def _run_health_check(self):
        """运行健康检查并显示结果"""
        self.health_text.delete('1.0', 'end')
        results = self.health_checker.check_backup_health()

        ok_count = sum(1 for s, _ in results if s == 'ok')
        warn_count = sum(1 for s, _ in results if s == 'warn')
        error_count = sum(1 for s, _ in results if s == 'error')

        for status, msg in results:
            icon = {'ok': '✓', 'warn': '⚠', 'error': '✗'}[status]
            color_tag = {'ok': 'success', 'warn': 'warn', 'error': 'error'}[status]
            self.health_text.insert('end', f"{icon} {msg}\n", color_tag)

        summary = f"\n检查结果: {ok_count} 通过, {warn_count} 警告, {error_count} 错误"
        self.health_text.insert('end', summary, 'info')

    def _start_backup(self):
        """开始备份（后台线程）"""
        self.backup_btn.configure(state='disabled', text="备份中...")
        self.progress_bar.set(0)
        self.log_text.delete('1.0', 'end')

        # 确定输出路径
        desktop = PathDetector().get_desktop()
        timestamp = datetime.now().strftime('%Y%m%d')
        output_path = os.path.join(desktop, f'cc-switch-migration-{timestamp}.zip')

        def progress_cb(pct, msg):
            self.after(0, lambda: self._update_progress(pct / 100, msg))

        def run():
            try:
                result = self.engine.backup(output_path, progress_callback=progress_cb)
                self.after(0, lambda: self._backup_done(result))
            except Exception as e:
                self.after(0, lambda: self._backup_error(str(e)))

        threading.Thread(target=run, daemon=True).start()

    def _update_progress(self, value, msg):
        self.progress_bar.set(value)
        self.progress_label.configure(text=msg)
        if msg and not msg.startswith('就绪'):
            self.log_text.insert('end', f"{msg}\n")
            self.log_text.see('end')

    def _backup_done(self, result):
        self.progress_bar.set(1.0)
        self.progress_label.configure(text="备份完成!")
        self.backup_btn.configure(state='normal', text="开始备份")

        if result.get('success'):
            self.log_text.insert('end', f"\n{'='*50}\n")
            self.log_text.insert('end', f"备份成功!\n", 'success')
            self.log_text.insert('end', f"文件: {result['output_path']}\n")
            self.log_text.insert('end', f"大小: {result['size_mb']} MB\n")
            self.log_text.insert('end', f"Skills: {result['skills_count']} 个\n")
            self.log_text.insert('end', f"MCPs: {result['mcps_count']} 个\n")
            self.log_text.insert('end', f"Providers: {result['providers_count']} 个\n")

            self.path_label.configure(text=f"输出: {result['output_path']}")
            messagebox.showinfo("备份完成", f"迁移包已生成:\n{result['output_path']}\n\n大小: {result['size_mb']} MB")

    def _backup_error(self, error):
        self.backup_btn.configure(state='normal', text="开始备份")
        self.progress_label.configure(text="备份失败")
        self.log_text.insert('end', f"\n错误: {error}\n", 'error')
        messagebox.showerror("备份失败", error)


# =============================================================================
#  恢复视图
# =============================================================================

class RestoreView(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color=COLORS['bg'])
        self.app = app
        self.engine = None
        self.package_path = None

        # 标题
        title = ctk.CTkLabel(self, text="恢复", font=FONT_TITLE, text_color=COLORS['accent'])
        title.pack(anchor='w', pady=(0, 8))

        # 包选择区域
        pkg_frame = ctk.CTkFrame(self, fg_color=COLORS['card'], corner_radius=6, border_width=1, border_color=COLORS['border'])
        pkg_frame.pack(fill='x', pady=(0, 8))

        pkg_label = ctk.CTkLabel(pkg_frame, text="选择迁移包", font=FONT_SECTION, text_color=COLORS['text'])
        pkg_label.pack(anchor='w', padx=14, pady=(8, 6))

        select_frame = ctk.CTkFrame(pkg_frame, fg_color='transparent')
        select_frame.pack(fill='x', padx=14, pady=(0, 8))

        self.path_entry = ctk.CTkEntry(select_frame, font=FONT_MONO, placeholder_text="点击右侧按钮选择 .zip 迁移包...",
                                       fg_color=COLORS['bg'], border_color=COLORS['border'], corner_radius=4)
        self.path_entry.pack(side='left', fill='x', expand=True, padx=(0, 6))

        browse_btn = ctk.CTkButton(
            select_frame, text="浏览", width=70, font=FONT_BODY,
            fg_color=COLORS['accent'], hover_color=COLORS['accent_hover'],
            corner_radius=4,
            command=self._browse_package
        )
        browse_btn.pack(side='left')

        # 环境检测区域
        env_frame = ctk.CTkFrame(self, fg_color=COLORS['card'], corner_radius=6, border_width=1, border_color=COLORS['border'])
        env_frame.pack(fill='x', pady=(0, 8))

        env_title = ctk.CTkLabel(env_frame, text="环境检测 & 路径映射", font=FONT_SECTION, text_color=COLORS['text'])
        env_title.pack(anchor='w', padx=14, pady=(8, 6))

        self.env_text = ctk.CTkTextbox(env_frame, height=70, font=FONT_MONO, fg_color=COLORS['bg'], text_color=COLORS['text'], corner_radius=4)
        self.env_text.pack(fill='x', padx=14, pady=(0, 8))
        _configure_text_tags(self.env_text)
        self.env_text.insert('end', "请先选择迁移包...\n")

        # 冲突策略
        strategy_frame = ctk.CTkFrame(self, fg_color=COLORS['card'], corner_radius=6, border_width=1, border_color=COLORS['border'])
        strategy_frame.pack(fill='x', pady=(0, 8))

        strategy_label = ctk.CTkLabel(strategy_frame, text="冲突处理策略", font=FONT_SECTION, text_color=COLORS['text'])
        strategy_label.pack(anchor='w', padx=14, pady=(8, 6))

        self.strategy_var = ctk.StringVar(value="merge")
        strategies = [
            ("merge", "合并（推荐）- 跳过已有的，只添加新的"),
            ("overwrite", "覆盖 - 用迁移包替换所有"),
            ("skip", "跳过 - 只恢复不存在的"),
        ]
        for value, text in strategies:
            rb = ctk.CTkRadioButton(
                strategy_frame, text=text, font=FONT_SMALL, variable=self.strategy_var,
                value=value, fg_color=COLORS['accent'], text_color=COLORS['text']
            )
            rb.pack(anchor='w', padx=18, pady=2)

        # 进度区域
        self.progress_label = ctk.CTkLabel(self, text="就绪", font=FONT_SMALL, text_color=COLORS['text_dim'])
        self.progress_label.pack(anchor='w', pady=(4, 2))

        self.progress_bar = ctk.CTkProgressBar(self, height=6, corner_radius=3, progress_color=COLORS['accent'])
        self.progress_bar.pack(fill='x', pady=(0, 8))
        self.progress_bar.set(0)

        # 日志区域
        self.log_text = ctk.CTkTextbox(self, height=70, font=FONT_MONO, fg_color=COLORS['card'], text_color=COLORS['text'], corner_radius=4)
        self.log_text.pack(fill='both', expand=True, pady=(0, 8))
        _configure_text_tags(self.log_text)

        # 恢复按钮
        self.restore_btn = ctk.CTkButton(
            self, text="开始恢复", font=FONT_BODY,
            fg_color=COLORS['accent'], hover_color=COLORS['accent_hover'],
            corner_radius=4, height=34, state='disabled',
            command=self._start_restore
        )
        self.restore_btn.pack(side='right', pady=(4, 0))

    def _browse_package(self):
        """选择迁移包"""
        path = filedialog.askopenfilename(
            title="选择迁移包",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")]
        )
        if path:
            self.package_path = path
            self.path_entry.delete(0, 'end')
            self.path_entry.insert(0, path)
            self._load_package()

    def _load_package(self):
        """加载迁移包并显示环境检测"""
        try:
            self.engine = RestoreEngine(self.package_path)
            self.engine.load_package()

            # 检测环境
            mappings = self.engine.detect_environment()

            # 显示信息
            self.env_text.delete('1.0', 'end')

            manifest = self.engine.manifest
            self.env_text.insert('end', f"迁移包信息:\n", 'info')
            self.env_text.insert('end', f"  备份时间: {manifest.get('backup_date', 'N/A')}\n")
            self.env_text.insert('end', f"  源电脑: {manifest.get('computer_name', 'N/A')} / 用户: {manifest.get('username', 'N/A')}\n")
            self.env_text.insert('end', f"  Skills: {manifest.get('skills_count', 0)} | MCPs: {manifest.get('mcps_count', 0)} | Providers: {manifest.get('providers_count', 0)}\n\n")

            self.env_text.insert('end', f"当前环境:\n", 'info')
            tools = mappings.get('tools', {})
            for name, installed in tools.items():
                icon = "✓" if installed else "✗"
                self.env_text.insert('end', f"  {icon} {name}\n", 'success' if installed else 'error')

            # 路径映射
            if 'python' in mappings:
                py = mappings['python']
                if py.get('old') and py.get('new') and py['old'] != py['new']:
                    self.env_text.insert('end', f"\n路径变更:\n", 'warn')
                    self.env_text.insert('end', f"  Python: {py['old']}\n  → {py['new']}\n", 'success')

            if 'username' in mappings:
                un = mappings['username']
                if un.get('old') != un.get('new'):
                    self.env_text.insert('end', f"  用户名: {un['old']} → {un['new']}\n", 'warn')

            if manifest.get('contains_api_keys'):
                self.env_text.insert('end', f"\n⚠ 此迁移包包含 API 密钥，请注意安全\n", 'warn')

            self.restore_btn.configure(state='normal')

        except Exception as e:
            self.env_text.delete('1.0', 'end')
            self.env_text.insert('end', f"加载失败: {e}\n", 'error')
            self.restore_btn.configure(state='disabled')
            messagebox.showerror("加载失败", str(e))

    def _start_restore(self):
        """开始恢复（后台线程）"""
        if not self.engine:
            return

        # 确认对话框
        if not messagebox.askyesno("确认恢复", "恢复将修改 CC Switch 数据库和配置文件。\n\n建议先关闭 CC Switch 应用。\n\n是否继续？"):
            return

        self.restore_btn.configure(state='disabled', text="恢复中...")
        self.progress_bar.set(0)
        self.log_text.delete('1.0', 'end')

        strategy = self.strategy_var.get()

        def progress_cb(pct, msg):
            self.after(0, lambda: self._update_progress(pct / 100, msg))

        def run():
            try:
                result = self.engine.restore(conflict_strategy=strategy, progress_callback=progress_cb)
                self.after(0, lambda: self._restore_done(result))
            except Exception as e:
                self.after(0, lambda: self._restore_error(str(e)))

        threading.Thread(target=run, daemon=True).start()

    def _update_progress(self, value, msg):
        self.progress_bar.set(value)
        self.progress_label.configure(text=msg)
        if msg:
            self.log_text.insert('end', f"{msg}\n")
            self.log_text.see('end')

    def _restore_done(self, result):
        self.progress_bar.set(1.0)
        self.progress_label.configure(text="恢复完成!")
        self.restore_btn.configure(state='normal', text="开始恢复")

        # 显示报告
        report = result.get('report', [])
        for status, msg in report:
            self.log_text.insert('end', f"{status}: {msg}\n")
        self.log_text.see('end')

        report_path = result.get('report_path', '')
        if report_path:
            self.log_text.insert('end', f"\n迁移报告已生成: {report_path}\n", 'success')
            messagebox.showinfo("恢复完成", f"恢复完成!\n\n迁移报告已在浏览器中打开:\n{report_path}")

    def _restore_error(self, error):
        self.restore_btn.configure(state='normal', text="开始恢复")
        self.progress_label.configure(text="恢复失败")
        self.log_text.insert('end', f"\n错误: {error}\n", 'error')
        messagebox.showerror("恢复失败", error)


# =============================================================================
#  选择性迁移视图
# =============================================================================

class SelectiveView(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color=COLORS['bg'])
        self.app = app
        self.engine = BackupEngine()
        self.skill_vars = {}
        self.mcp_vars = {}
        self.provider_vars = {}

        # 标题
        title = ctk.CTkLabel(self, text="选择性迁移", font=FONT_TITLE, text_color=COLORS['accent'])
        title.pack(anchor='w', pady=(0, 3))

        subtitle = ctk.CTkLabel(self, text="勾选要迁移的项目，取消勾选的不迁移", font=FONT_SMALL, text_color=COLORS['text_dim'])
        subtitle.pack(anchor='w', pady=(0, 8))

        # 可滚动区域
        scroll = ctk.CTkScrollableFrame(self, fg_color=COLORS['bg'], corner_radius=0)
        scroll.pack(fill='both', expand=True, pady=(0, 8))

        # 加载数据
        self._load_data(scroll)

        # 进度区域
        self.progress_label = ctk.CTkLabel(self, text="就绪", font=FONT_SMALL, text_color=COLORS['text_dim'])
        self.progress_label.pack(anchor='w')

        self.progress_bar = ctk.CTkProgressBar(self, height=5, corner_radius=3, progress_color=COLORS['accent'])
        self.progress_bar.pack(fill='x', pady=(2, 8))
        self.progress_bar.set(0)

        # 按钮区域
        btn_frame = ctk.CTkFrame(self, fg_color='transparent')
        btn_frame.pack(fill='x')

        select_all_btn = ctk.CTkButton(
            btn_frame, text="全选", width=70, font=FONT_SMALL,
            fg_color=COLORS['card'], hover_color=COLORS['card_hover'],
            corner_radius=4, border_width=1, border_color=COLORS['border'],
            text_color=COLORS['text'],
            command=self._select_all
        )
        select_all_btn.pack(side='left', padx=(0, 4))

        deselect_all_btn = ctk.CTkButton(
            btn_frame, text="取消全选", width=70, font=FONT_SMALL,
            fg_color=COLORS['card'], hover_color=COLORS['card_hover'],
            corner_radius=4, border_width=1, border_color=COLORS['border'],
            text_color=COLORS['text'],
            command=self._deselect_all
        )
        deselect_all_btn.pack(side='left', padx=(0, 4))

        self.backup_btn = ctk.CTkButton(
            btn_frame, text="备份选中项", font=FONT_BODY,
            fg_color=COLORS['accent'], hover_color=COLORS['accent_hover'],
            corner_radius=4, height=30,
            command=self._start_selective_backup
        )
        self.backup_btn.pack(side='right')

    def _load_data(self, parent):
        """从数据库加载数据并显示"""
        home = os.path.expanduser('~')
        db_path = os.path.join(home, '.cc-switch', 'cc-switch.db')

        if not os.path.isfile(db_path):
            ctk.CTkLabel(parent, text="CC Switch 数据库不存在", font=FONT_BODY, text_color=COLORS['error']).pack(pady=20)
            return

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Skills
        try:
            skills = conn.execute('SELECT name, description FROM skills ORDER BY name').fetchall()
            skills_dicts = [dict(r) for r in skills]
        except sqlite3.OperationalError:
            skills_dicts = []
        self._create_section(parent, f"Skills ({len(skills_dicts)} 个)", skills_dicts, self.skill_vars, 'name', 'description')

        # MCPs
        try:
            mcps = conn.execute('SELECT name, description FROM mcp_servers ORDER BY name').fetchall()
            mcps_dicts = [dict(r) for r in mcps]
        except sqlite3.OperationalError:
            mcps_dicts = []
        self._create_section(parent, f"MCP Servers ({len(mcps_dicts)} 个)", mcps_dicts, self.mcp_vars, 'name', 'description')

        # Providers
        try:
            providers = conn.execute('SELECT id, name, app_type, category FROM providers ORDER BY name').fetchall()
            provider_items = [{'name': f"{r['name']} ({r['app_type']})", 'description': r['category'] or '', 'id': r['id']} for r in providers]
        except (sqlite3.OperationalError, IndexError):
            provider_items = []
        self._create_section(parent, f"API Providers ({len(provider_items)} 个)", provider_items, self.provider_vars, 'name', 'description', id_field='id')

        conn.close()

    def _create_section(self, parent, title, items, var_dict, name_field, desc_field, id_field=None):
        """创建一个带复选框的区域。id_field 不为 None 时用该字段值作为 var_dict 的键。"""
        section = ctk.CTkFrame(parent, fg_color=COLORS['card'], corner_radius=6, border_width=1, border_color=COLORS['border'])
        section.pack(fill='x', pady=(0, 8))

        label = ctk.CTkLabel(section, text=title, font=FONT_SECTION, text_color=COLORS['accent'])
        label.pack(anchor='w', padx=14, pady=(8, 6))

        if not items:
            ctk.CTkLabel(section, text="无数据", font=FONT_SMALL, text_color=COLORS['text_dim']).pack(anchor='w', padx=18, pady=(0, 8))
            return

        for i, item in enumerate(items):
            display_name = item[name_field]
            desc = item.get(desc_field, '') or ''
            key = item[id_field] if id_field and id_field in item else display_name

            var = ctk.BooleanVar(value=True)
            var_dict[key] = var

            cb = ctk.CTkCheckBox(
                section, text=f"{display_name}" + (f" - {desc[:50]}" if desc else ""),
                font=FONT_SMALL, variable=var,
                fg_color=COLORS['accent'], hover_color=COLORS['accent_hover'],
                text_color=COLORS['text']
            )
            cb.pack(anchor='w', padx=18, pady=1)

        # 底部间距
        ctk.CTkLabel(section, text="", font=FONT_SMALL).pack(pady=(0, 4))

    def _select_all(self):
        for var in list(self.skill_vars.values()) + list(self.mcp_vars.values()) + list(self.provider_vars.values()):
            var.set(True)

    def _deselect_all(self):
        for var in list(self.skill_vars.values()) + list(self.mcp_vars.values()) + list(self.provider_vars.values()):
            var.set(False)

    def _start_selective_backup(self):
        """开始选择性备份"""
        selected_skills = [name for name, var in self.skill_vars.items() if var.get()]
        selected_mcps = [name for name, var in self.mcp_vars.items() if var.get()]
        selected_providers = [name for name, var in self.provider_vars.items() if var.get()]

        if not selected_skills and not selected_mcps and not selected_providers:
            messagebox.showwarning("未选择", "请至少选择一个要迁移的项目")
            return

        self.backup_btn.configure(state='disabled', text="备份中...")
        self.progress_bar.set(0)

        desktop = PathDetector().get_desktop()
        timestamp = datetime.now().strftime('%Y%m%d')
        output_path = os.path.join(desktop, f'cc-switch-migration-selective-{timestamp}.zip')

        def progress_cb(pct, msg):
            self.after(0, lambda: self._update_progress(pct / 100, msg))

        def run():
            try:
                result = self.engine.backup(
                    output_path,
                    selected_skills=selected_skills,
                    selected_mcps=selected_mcps,
                    selected_providers=selected_providers,
                    progress_callback=progress_cb
                )
                self.after(0, lambda: self._backup_done(result))
            except Exception as e:
                self.after(0, lambda: self._backup_error(str(e)))

        threading.Thread(target=run, daemon=True).start()

    def _update_progress(self, value, msg):
        self.progress_bar.set(value)
        self.progress_label.configure(text=msg)

    def _backup_done(self, result):
        self.progress_bar.set(1.0)
        self.progress_label.configure(text="备份完成!")
        self.backup_btn.configure(state='normal', text="备份选中项")

        if result.get('success'):
            messagebox.showinfo(
                "备份完成",
                f"选择性迁移包已生成:\n{result['output_path']}\n\n"
                f"Skills: {result['skills_count']} | MCPs: {result['mcps_count']} | Providers: {result['providers_count']}\n"
                f"大小: {result['size_mb']} MB"
            )

    def _backup_error(self, error):
        self.backup_btn.configure(state='normal', text="备份选中项")
        self.progress_label.configure(text="备份失败")
        messagebox.showerror("备份失败", error)


# =============================================================================
#  入口
# =============================================================================

if __name__ == '__main__':
    app = App()
    app.mainloop()
