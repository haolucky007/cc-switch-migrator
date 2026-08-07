"""
CC Switch Skills & MCP 迁移工具 - 核心模块

包含路径检测、健康检查、备份引擎、恢复引擎四大核心组件。
不依赖第三方库，仅使用 Python 标准库。
"""

import sqlite3
import json
import os
import shutil
import zipfile
import subprocess
import tempfile
import webbrowser
import glob
import ctypes
import socket
from datetime import datetime


# =============================================================================
#  数据库表定义（用于目标数据库不存在时创建表结构）
# =============================================================================

# 已知真实 Schema 的表（来自 CC Switch 数据库实际结构）
REAL_TABLE_DDLS = {
    'skills': '''CREATE TABLE IF NOT EXISTS skills (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        directory TEXT NOT NULL,
        repo_owner TEXT,
        repo_name TEXT,
        repo_branch TEXT DEFAULT 'main',
        readme_url TEXT,
        enabled_claude BOOLEAN NOT NULL DEFAULT 0,
        enabled_codex BOOLEAN NOT NULL DEFAULT 0,
        enabled_gemini BOOLEAN NOT NULL DEFAULT 0,
        enabled_opencode BOOLEAN NOT NULL DEFAULT 0,
        enabled_hermes BOOLEAN NOT NULL DEFAULT 0,
        installed_at INTEGER NOT NULL DEFAULT 0,
        content_hash TEXT,
        updated_at INTEGER NOT NULL DEFAULT 0
    )''',
    'mcp_servers': '''CREATE TABLE IF NOT EXISTS mcp_servers (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        server_config TEXT NOT NULL,
        description TEXT,
        homepage TEXT,
        docs TEXT,
        tags TEXT NOT NULL DEFAULT '[]',
        enabled_claude BOOLEAN NOT NULL DEFAULT 0,
        enabled_codex BOOLEAN NOT NULL DEFAULT 0,
        enabled_gemini BOOLEAN NOT NULL DEFAULT 0,
        enabled_opencode BOOLEAN NOT NULL DEFAULT 0,
        enabled_hermes BOOLEAN NOT NULL DEFAULT 0
    )''',
}

# 各表用于存在性检查的主键列（按迁移需求定义）
TABLE_PRIMARY_KEYS = {
    'skills': 'name',
    'mcp_servers': 'name',
    'providers': 'id',
    'settings': 'key',
    'skill_repos': 'owner',
}

# 需要导出/合并的表列表
EXPORT_TABLES = ['skills', 'mcp_servers', 'providers', 'settings', 'skill_repos']


# =============================================================================
#  PathDetector - 路径检测器
# =============================================================================

class PathDetector:
    """检测系统环境中的 Python、Node.js、已安装工具等信息。"""

    def detect_python(self):
        """
        扫描 C:\\D:\\E:\\F:\\ 盘的 Python 安装路径（检查 python.exe），
        也检查 PATH 中 where python，也检查用户 AppData\\Local\\Programs\\Python。
        返回正斜杠路径如 "D:/Pyhotn3.13.14/python.exe"，未找到返回 None。
        """
        candidates = []

        # 1. 扫描 C:\D:\E:\F:\ 盘根目录下的各目录
        for drive in ['C', 'D', 'E', 'F']:
            drive_root = f'{drive}:\\'
            if not os.path.exists(drive_root):
                continue
            try:
                for entry in os.listdir(drive_root):
                    exe_path = os.path.join(drive_root, entry, 'python.exe')
                    if os.path.isfile(exe_path):
                        candidates.append(exe_path)
            except (PermissionError, OSError):
                continue

        # 2. 检查 Program Files 目录
        for drive in ['C', 'D']:
            for pf_name in ['Program Files', 'Program Files (x86)']:
                pf_path = os.path.join(f'{drive}:\\', pf_name)
                if os.path.isdir(pf_path):
                    try:
                        for entry in os.listdir(pf_path):
                            exe_path = os.path.join(pf_path, entry, 'python.exe')
                            if os.path.isfile(exe_path):
                                candidates.append(exe_path)
                    except (PermissionError, OSError):
                        continue

        # 3. 使用 where python 检查 PATH
        try:
            result = subprocess.run(
                'where python',
                capture_output=True, text=True, shell=True, timeout=5
            )
            for line in result.stdout.strip().split('\n'):
                line = line.strip()
                if line and os.path.isfile(line):
                    candidates.append(line)
        except Exception:
            pass

        # 4. 检查 AppData\Local\Programs\Python
        local_appdata = os.environ.get('LOCALAPPDATA', '')
        if local_appdata:
            python_base = os.path.join(local_appdata, 'Programs', 'Python')
            if os.path.isdir(python_base):
                try:
                    for entry in os.listdir(python_base):
                        exe_path = os.path.join(python_base, entry, 'python.exe')
                        if os.path.isfile(exe_path):
                            candidates.append(exe_path)
                except (PermissionError, OSError):
                    pass

        # 去重并返回第一个有效路径（正斜杠形式）
        seen = set()
        for c in candidates:
            norm = os.path.normpath(c).lower()
            if norm not in seen:
                seen.add(norm)
                if os.path.isfile(c):
                    return c.replace('\\', '/')

        return None

    def detect_node(self):
        """用 where node 检测 Node.js 路径，返回正斜杠路径或 None。"""
        try:
            result = subprocess.run(
                'where node',
                capture_output=True, text=True, shell=True, timeout=5
            )
            for line in result.stdout.strip().split('\n'):
                line = line.strip()
                if line and os.path.isfile(line):
                    return line.replace('\\', '/')
        except Exception:
            pass
        return None

    def detect_installed_tools(self):
        """
        检测 CC Switch、Claude Code、Codex、OpenCode 是否安装。
        返回 dict: {'CC Switch': bool, 'Claude Code': bool, ...}
        """
        home = os.path.expanduser('~')
        return {
            'CC Switch': os.path.isdir(os.path.join(home, '.cc-switch')),
            'Claude Code': os.path.exists(os.path.join(home, '.claude.json')),
            'Codex': os.path.exists(os.path.join(home, '.codex', 'config.toml')),
            'OpenCode': os.path.exists(os.path.join(home, '.config', 'opencode', 'opencode.json')),
        }

    def get_username(self):
        """返回当前用户名。"""
        return os.environ.get('USERNAME', os.environ.get('USER', ''))

    def get_desktop(self):
        """
        用 ctypes.windll.shell32.SHGetFolderPath 获取真实桌面路径。
        不使用 %USERPROFILE%\\Desktop，因为桌面可能被重定向。
        """
        CSIDL_DESKTOP = 0x0010
        buf = ctypes.create_unicode_buffer(260)
        try:
            ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_DESKTOP, None, 0, buf)
            path = buf.value
            if path and os.path.isdir(path):
                return path
        except Exception:
            pass
        # 回退方案
        return os.path.join(os.path.expanduser('~'), 'Desktop')


# =============================================================================
#  HealthChecker - 健康检查器
# =============================================================================

class HealthChecker:
    """备份前和恢复后的健康检查。"""

    def __init__(self):
        self.home = os.path.expanduser('~')
        self.cc_switch_dir = os.path.join(self.home, '.cc-switch')
        self.db_path = os.path.join(self.cc_switch_dir, 'cc-switch.db')
        self.skills_dir = os.path.join(self.cc_switch_dir, 'skills')

    def check_backup_health(self):
        """
        备份前检查：
        - CC Switch 目录存在
        - 数据库可读（SELECT COUNT(*) FROM skills）
        - Skills 目录中有多少个 skill，每个是否有 SKILL.md
        - MCP 配置 JSON 是否合法
        - 配置文件是否存在
        返回 list of (status, message)，status 为 'ok'/'warn'/'error'。
        """
        results = []

        # 1. CC Switch 目录存在
        if os.path.isdir(self.cc_switch_dir):
            results.append(('ok', f'CC Switch 目录存在: {self.cc_switch_dir}'))
        else:
            results.append(('error', f'CC Switch 目录不存在: {self.cc_switch_dir}'))
            return results

        # 2. 数据库可读
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM skills')
            count = cursor.fetchone()[0]
            results.append(('ok', f'数据库可读，skills 表有 {count} 条记录'))
            conn.close()
        except Exception as e:
            results.append(('error', f'数据库不可读: {e}'))

        # 3. Skills 目录检查
        if os.path.isdir(self.skills_dir):
            skill_dirs = [
                d for d in os.listdir(self.skills_dir)
                if os.path.isdir(os.path.join(self.skills_dir, d))
            ]
            results.append(('ok', f'Skills 目录有 {len(skill_dirs)} 个 skill'))

            missing_skill_md = []
            for skill in skill_dirs:
                skill_md = os.path.join(self.skills_dir, skill, 'SKILL.md')
                if not os.path.exists(skill_md):
                    missing_skill_md.append(skill)

            if missing_skill_md:
                results.append(('warn', f'以下 skill 缺少 SKILL.md: {", ".join(missing_skill_md)}'))
            else:
                results.append(('ok', '所有 skill 都有 SKILL.md'))
        else:
            results.append(('warn', f'Skills 目录不存在: {self.skills_dir}'))

        # 4. MCP 配置 JSON 是否合法
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT name, server_config FROM mcp_servers')
            rows = cursor.fetchall()
            invalid = []
            for name, config in rows:
                try:
                    if isinstance(config, str):
                        json.loads(config)
                except (json.JSONDecodeError, TypeError):
                    invalid.append(name)
            if invalid:
                results.append(('warn', f'以下 MCP 配置 JSON 无效: {", ".join(invalid)}'))
            else:
                results.append(('ok', f'所有 {len(rows)} 个 MCP 配置 JSON 合法'))
            conn.close()
        except Exception as e:
            results.append(('warn', f'无法检查 MCP 配置: {e}'))

        # 5. 配置文件是否存在
        config_files = [
            ('Claude Code', os.path.join(self.home, '.claude.json')),
            ('Codex', os.path.join(self.home, '.codex', 'config.toml')),
            ('OpenCode', os.path.join(self.home, '.config', 'opencode', 'opencode.json')),
        ]
        for name, path in config_files:
            if os.path.exists(path):
                results.append(('ok', f'{name} 配置文件存在'))
            else:
                results.append(('warn', f'{name} 配置文件不存在'))

        return results

    def check_restore_health(self, path_mappings):
        """
        恢复后验证：
        - 所有 Skill 目录存在且有 SKILL.md
        - 符号链接有效（.claude/skills, .codex/skills, .config/opencode/skills 下）
        - Python 路径有效
        - 数据库可读
        返回 list of (status, message)。
        """
        results = []
        home = os.path.expanduser('~')
        skills_dir = os.path.join(home, '.cc-switch', 'skills')

        # 1. 所有 skill 目录存在且有 SKILL.md
        if os.path.isdir(skills_dir):
            skill_dirs = [
                d for d in os.listdir(skills_dir)
                if os.path.isdir(os.path.join(skills_dir, d))
            ]
            missing = []
            for skill in skill_dirs:
                skill_md = os.path.join(skills_dir, skill, 'SKILL.md')
                if not os.path.exists(skill_md):
                    missing.append(skill)
            if missing:
                results.append(('warn', f'以下 skill 缺少 SKILL.md: {", ".join(missing)}'))
            else:
                results.append(('ok', f'所有 {len(skill_dirs)} 个 skill 目录正常'))
        else:
            results.append(('error', f'Skills 目录不存在: {skills_dir}'))

        # 2. 符号链接有效
        symlink_dirs = [
            os.path.join(home, '.claude', 'skills'),
            os.path.join(home, '.codex', 'skills'),
            os.path.join(home, '.config', 'opencode', 'skills'),
        ]
        for link_path in symlink_dirs:
            if os.path.islink(link_path):
                if os.path.exists(link_path):
                    results.append(('ok', f'符号链接有效: {link_path}'))
                else:
                    results.append(('warn', f'符号链接目标无效: {link_path}'))
            elif os.path.isdir(link_path):
                results.append(('ok', f'目录存在（非符号链接）: {link_path}'))
            else:
                results.append(('warn', f'符号链接不存在: {link_path}'))

        # 3. Python 路径有效
        python_path = path_mappings.get('python', {}).get('new')
        if python_path and os.path.isfile(python_path):
            results.append(('ok', f'Python 路径有效: {python_path}'))
        elif python_path:
            results.append(('error', f'Python 路径无效（文件不存在）: {python_path}'))
        else:
            results.append(('warn', '未检测到 Python 路径'))

        # 4. 数据库可读
        db_path = os.path.join(home, '.cc-switch', 'cc-switch.db')
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM skills')
            count = cursor.fetchone()[0]
            results.append(('ok', f'数据库可读，skills 表有 {count} 条记录'))
            conn.close()
        except Exception as e:
            results.append(('error', f'数据库不可读: {e}'))

        return results


# =============================================================================
#  BackupEngine - 备份引擎
# =============================================================================

class BackupEngine:
    """创建 CC Switch 迁移包。"""

    def __init__(self):
        self.home = os.path.expanduser('~')
        self.cc_switch_dir = os.path.join(self.home, '.cc-switch')
        self.db_path = os.path.join(self.cc_switch_dir, 'cc-switch.db')
        self.skills_dir = os.path.join(self.cc_switch_dir, 'skills')

    def backup(self, output_path, selected_skills=None, selected_mcps=None,
               selected_providers=None, progress_callback=None):
        """
        执行备份，打包为 zip。

        参数:
            output_path: 输出 zip 文件路径
            selected_skills: 选中的 skill 名称列表，None 表示全部
            selected_mcps: 选中的 MCP 名称列表，None 表示全部
            selected_providers: 选中的 provider ID 列表，None 表示全部
            progress_callback: 回调函数 callback(progress_percent, message)

        返回:
            dict: {success, output_path, skills_count, mcps_count, providers_count, size_mb}
        """
        def progress(pct, msg):
            if progress_callback:
                progress_callback(pct, msg)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        temp_dir = tempfile.mkdtemp(prefix='cc_backup_')

        try:
            # 1. 导出数据库
            progress(10, '正在导出数据库...')
            db_export = self._export_database(
                self.db_path, selected_skills, selected_mcps, selected_providers
            )
            with open(os.path.join(temp_dir, 'database_export.json'), 'w',
                      encoding='utf-8') as f:
                json.dump(db_export, f, ensure_ascii=False, indent=2)

            # 2. 复制 skills 目录
            progress(30, '正在复制 Skills 文件...')
            if os.path.isdir(self.skills_dir):
                dst_skills = os.path.join(temp_dir, 'skills')
                if selected_skills is not None:
                    # 只复制选中的 skill
                    os.makedirs(dst_skills, exist_ok=True)
                    for skill_name in selected_skills:
                        src_skill = os.path.join(self.skills_dir, skill_name)
                        if os.path.isdir(src_skill):
                            shutil.copytree(src_skill, os.path.join(dst_skills, skill_name))
                else:
                    shutil.copytree(self.skills_dir, dst_skills)

            # 3. 复制 settings.json
            progress(50, '正在复制 settings.json...')
            settings_path = os.path.join(self.cc_switch_dir, 'settings.json')
            if os.path.exists(settings_path):
                shutil.copy2(settings_path, os.path.join(temp_dir, 'settings.json'))

            # 4. 复制 .claude/mcp-servers/ 目录
            progress(60, '正在复制 MCP 服务器文件...')
            mcp_servers_dir = os.path.join(self.home, '.claude', 'mcp-servers')
            if os.path.isdir(mcp_servers_dir):
                shutil.copytree(mcp_servers_dir, os.path.join(temp_dir, 'mcp-servers'))

            # 5. 复制配置文件
            progress(70, '正在复制配置文件...')
            config_mappings = [
                (os.path.join(self.home, '.claude.json'), 'claude.json'),
                (os.path.join(self.home, '.codex', 'config.toml'), 'codex_config.toml'),
                (os.path.join(self.home, '.config', 'opencode', 'opencode.json'), 'opencode.json'),
            ]
            for src, dst in config_mappings:
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(temp_dir, dst))

            # 6. 生成 manifest
            progress(80, '正在生成 manifest...')
            manifest = self._generate_manifest(db_export, timestamp)
            with open(os.path.join(temp_dir, 'manifest.json'), 'w',
                      encoding='utf-8') as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)

            # 7. 生成 restore.bat
            progress(85, '正在生成 restore.bat...')
            self._generate_restore_bat(os.path.join(temp_dir, 'restore.bat'))

            # 8. 打包为 zip
            progress(90, '正在打包为 zip...')
            if not output_path.lower().endswith('.zip'):
                output_path += '.zip'
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, temp_dir)
                        zf.write(file_path, arcname)

            progress(100, '备份完成!')

            size_bytes = os.path.getsize(output_path)
            size_mb = round(size_bytes / (1024 * 1024), 2)

            return {
                'success': True,
                'output_path': output_path,
                'skills_count': len(db_export.get('skills', [])),
                'mcps_count': len(db_export.get('mcp_servers', [])),
                'providers_count': len(db_export.get('providers', [])),
                'size_mb': size_mb,
            }
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _export_database(self, db_path, selected_skills=None,
                         selected_mcps=None, selected_providers=None):
        """
        导出数据库表为 dict。
        如果有 selected 参数则只导出选中的记录。
        """
        export = {table: [] for table in EXPORT_TABLES}

        if not os.path.exists(db_path):
            return export

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # 获取已存在的表
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = {row[0] for row in cursor.fetchall()}

        # 导出 skills
        if 'skills' in existing_tables:
            if selected_skills is not None:
                if selected_skills:
                    placeholders = ','.join('?' * len(selected_skills))
                    cursor.execute(
                        f'SELECT * FROM skills WHERE name IN ({placeholders})',
                        selected_skills
                    )
                # 空列表则不导出
            else:
                cursor.execute('SELECT * FROM skills')
            for row in cursor.fetchall():
                export['skills'].append(dict(row))

        # 导出 mcp_servers
        if 'mcp_servers' in existing_tables:
            if selected_mcps is not None:
                if selected_mcps:
                    placeholders = ','.join('?' * len(selected_mcps))
                    cursor.execute(
                        f'SELECT * FROM mcp_servers WHERE name IN ({placeholders})',
                        selected_mcps
                    )
            else:
                cursor.execute('SELECT * FROM mcp_servers')
            for row in cursor.fetchall():
                export['mcp_servers'].append(dict(row))

        # 导出 providers
        if 'providers' in existing_tables:
            if selected_providers is not None:
                if selected_providers:
                    placeholders = ','.join('?' * len(selected_providers))
                    cursor.execute(
                        f'SELECT * FROM providers WHERE id IN ({placeholders})',
                        selected_providers
                    )
            else:
                cursor.execute('SELECT * FROM providers')
            for row in cursor.fetchall():
                export['providers'].append(dict(row))

        # 导出 settings（全量）
        if 'settings' in existing_tables:
            cursor.execute('SELECT * FROM settings')
            for row in cursor.fetchall():
                export['settings'].append(dict(row))

        # 导出 skill_repos（全量）
        if 'skill_repos' in existing_tables:
            cursor.execute('SELECT * FROM skill_repos')
            for row in cursor.fetchall():
                export['skill_repos'].append(dict(row))

        conn.close()
        return export

    def _generate_manifest(self, db_export, timestamp):
        """
        生成 manifest dict。
        path_dependencies: 遍历 mcp_servers 的 server_config JSON，
        检测 command/args/env 中的本地路径。
        """
        detector = PathDetector()
        python_path = detector.detect_python()

        skills_count = len(db_export.get('skills', []))
        mcps_count = len(db_export.get('mcp_servers', []))
        providers_count = len(db_export.get('providers', []))

        # 检测 MCP 配置中的本地路径依赖
        path_deps = []
        for mcp in db_export.get('mcp_servers', []):
            config_str = mcp.get('server_config', '')
            config = {}
            if isinstance(config_str, str):
                try:
                    config = json.loads(config_str)
                except (json.JSONDecodeError, TypeError):
                    config = {}
            elif isinstance(config_str, dict):
                config = config_str

            # 检查 command
            command = config.get('command', '')
            if command and self._is_local_path(command):
                path_deps.append(command)

            # 检查 args
            args = config.get('args', [])
            if isinstance(args, list):
                for arg in args:
                    if isinstance(arg, str) and self._is_local_path(arg):
                        path_deps.append(arg)

            # 检查 env
            env = config.get('env', {})
            if isinstance(env, dict):
                for v in env.values():
                    if isinstance(v, str) and self._is_local_path(v):
                        path_deps.append(v)

        # 去重
        path_deps = list(set(path_deps))

        manifest = {
            'version': '1.0',
            'backup_date': timestamp,
            'computer_name': socket.gethostname(),
            'username': detector.get_username(),
            'python_path': python_path,
            'skills_count': skills_count,
            'mcps_count': mcps_count,
            'providers_count': providers_count,
            'path_dependencies': path_deps,
            'contains_api_keys': True,
            'warning': '此备份包含 API 密钥等敏感信息，请妥善保管，不要分享给他人。',
        }

        return manifest

    @staticmethod
    def _is_local_path(text):
        """检测文本是否为本地路径（C:或D:开头、含 python/node、含 Users）。"""
        if not isinstance(text, str) or not text:
            return False
        # 检查盘符路径（C:\ D:\ 等）
        if len(text) >= 3 and text[0] in 'CDEFGHIJ' and text[1] == ':' and text[2] in '\\/':
            return True
        lower = text.lower()
        # 含 python 或 node 的路径
        if ('python' in lower or 'node' in lower) and ('/' in text or '\\' in text):
            return True
        # 含 Users 的路径
        if 'users' in lower and ('/' in text or '\\' in text):
            return True
        return False

    def _generate_restore_bat(self, path):
        """生成 restore.bat 文件（UTF-8 编码，含 chcp 65001）。"""
        content = (
            '@echo off\r\n'
            'chcp 65001 >nul\r\n'
            'echo ========================================\r\n'
            'echo   CC Switch 恢复脚本 (基础恢复)\r\n'
            'echo ========================================\r\n'
            'echo.\r\n'
            '\r\n'
            'set BACKUP_DIR=%~dp0\r\n'
            '\r\n'
            'echo [1/5] 恢复 Skills 目录...\r\n'
            'if exist "%BACKUP_DIR%skills" (\r\n'
            '    if not exist "%USERPROFILE%\\.cc-switch" mkdir "%USERPROFILE%\\.cc-switch"\r\n'
            '    xcopy "%BACKUP_DIR%skills" "%USERPROFILE%\\.cc-switch\\skills" /E /I /Y\r\n'
            '    echo Skills 目录恢复完成。\r\n'
            ') else (\r\n'
            '    echo 未找到 Skills 目录，跳过。\r\n'
            ')\r\n'
            'echo.\r\n'
            '\r\n'
            'echo [2/5] 恢复 settings.json...\r\n'
            'if exist "%BACKUP_DIR%settings.json" (\r\n'
            '    copy "%BACKUP_DIR%settings.json" "%USERPROFILE%\\.cc-switch\\settings.json" /Y\r\n'
            '    echo settings.json 恢复完成。\r\n'
            ') else (\r\n'
            '    echo 未找到 settings.json，跳过。\r\n'
            ')\r\n'
            'echo.\r\n'
            '\r\n'
            'echo [3/5] 恢复 MCP 服务器文件...\r\n'
            'if exist "%BACKUP_DIR%mcp-servers" (\r\n'
            '    if not exist "%USERPROFILE%\\.claude" mkdir "%USERPROFILE%\\.claude"\r\n'
            '    xcopy "%BACKUP_DIR%mcp-servers" "%USERPROFILE%\\.claude\\mcp-servers" /E /I /Y\r\n'
            '    echo MCP 服务器文件恢复完成。\r\n'
            ') else (\r\n'
            '    echo 未找到 MCP 服务器文件，跳过。\r\n'
            ')\r\n'
            'echo.\r\n'
            '\r\n'
            'echo [4/5] 恢复配置文件...\r\n'
            'if exist "%BACKUP_DIR%claude.json" (\r\n'
            '    copy "%BACKUP_DIR%claude.json" "%USERPROFILE%\\.claude.json" /Y\r\n'
            '    echo Claude Code 配置恢复完成。\r\n'
            ')\r\n'
            'if exist "%BACKUP_DIR%codex_config.toml" (\r\n'
            '    if not exist "%USERPROFILE%\\.codex" mkdir "%USERPROFILE%\\.codex"\r\n'
            '    copy "%BACKUP_DIR%codex_config.toml" "%USERPROFILE%\\.codex\\config.toml" /Y\r\n'
            '    echo Codex 配置恢复完成。\r\n'
            ')\r\n'
            'if exist "%BACKUP_DIR%opencode.json" (\r\n'
            '    if not exist "%USERPROFILE%\\.config\\opencode" mkdir "%USERPROFILE%\\.config\\opencode"\r\n'
            '    copy "%BACKUP_DIR%opencode.json" "%USERPROFILE%\\.config\\opencode\\opencode.json" /Y\r\n'
            '    echo OpenCode 配置恢复完成。\r\n'
            ')\r\n'
            'echo.\r\n'
            '\r\n'
            'echo [5/5] 恢复完成！\r\n'
            'echo.\r\n'
            'echo 注意：此为基础恢复脚本，不包含数据库和符号链接恢复。\r\n'
            'echo 建议使用 Python 迁移工具进行完整恢复。\r\n'
            'echo.\r\n'
            'pause\r\n'
        )
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)


# =============================================================================
#  RestoreEngine - 恢复引擎
# =============================================================================

class RestoreEngine:
    """从迁移包恢复 CC Switch 配置到新电脑。"""

    def __init__(self, package_path):
        self.package_path = package_path
        self.temp_dir = None
        self.manifest = None
        self.db_export = None
        self.report = []
        self.path_mappings = {}
        self.home = os.path.expanduser('~')
        self.cc_switch_dir = os.path.join(self.home, '.cc-switch')

    def load_package(self):
        """解压 zip 到临时目录，加载 manifest.json 和 database_export.json。"""
        self.temp_dir = tempfile.mkdtemp(prefix='cc_restore_')

        with zipfile.ZipFile(self.package_path, 'r') as zf:
            zf.extractall(self.temp_dir)

        # 加载 manifest
        manifest_path = os.path.join(self.temp_dir, 'manifest.json')
        if os.path.exists(manifest_path):
            with open(manifest_path, 'r', encoding='utf-8') as f:
                self.manifest = json.load(f)
        else:
            raise FileNotFoundError('迁移包中未找到 manifest.json')

        # 加载 database_export
        db_export_path = os.path.join(self.temp_dir, 'database_export.json')
        if os.path.exists(db_export_path):
            with open(db_export_path, 'r', encoding='utf-8') as f:
                self.db_export = json.load(f)
        else:
            self.db_export = {}

        return True

    def detect_environment(self):
        """
        检测新电脑环境，返回 path_mappings dict。
        包含 Python 路径、用户名、已安装工具的旧→新映射。
        """
        detector = PathDetector()

        old_python = self.manifest.get('python_path', '')
        new_python = detector.detect_python()

        old_username = self.manifest.get('username', '')
        new_username = detector.get_username()

        tools = detector.detect_installed_tools()

        self.path_mappings = {
            'python': {'old': old_python, 'new': new_python},
            'username': {'old': old_username, 'new': new_username},
            'tools': tools,
        }

        return self.path_mappings

    def _adapt_paths(self, text):
        """
        路径替换函数：
        - 替换 Python 路径（处理正斜杠和反斜杠两种形式）
        - 替换用户名路径（\\old_username\\ → \\new_username\\）
        返回替换后的文本。
        """
        if not isinstance(text, str):
            return text

        old_python = self.path_mappings.get('python', {}).get('old', '')
        new_python = self.path_mappings.get('python', {}).get('new', '')

        if old_python and new_python and old_python != new_python:
            # 正斜杠形式
            text = text.replace(old_python, new_python)
            # 反斜杠形式
            old_bs = old_python.replace('/', '\\')
            new_bs = new_python.replace('/', '\\')
            text = text.replace(old_bs, new_bs)
            # 双反斜杠形式（JSON 转义）
            old_dbs = old_bs.replace('\\', '\\\\')
            new_dbs = new_bs.replace('\\', '\\\\')
            text = text.replace(old_dbs, new_dbs)

            # Python 目录路径（不含 python.exe）
            old_dir = old_python.rsplit('/', 1)[0] if '/' in old_python else old_python
            new_dir = new_python.rsplit('/', 1)[0] if '/' in new_python else new_python
            # 正斜杠
            text = text.replace(old_dir, new_dir)
            # 反斜杠
            old_dir_bs = old_dir.replace('/', '\\')
            new_dir_bs = new_dir.replace('/', '\\')
            text = text.replace(old_dir_bs, new_dir_bs)
            # 双反斜杠
            old_dir_dbs = old_dir_bs.replace('\\', '\\\\')
            new_dir_dbs = new_dir_bs.replace('\\', '\\\\')
            text = text.replace(old_dir_dbs, new_dir_dbs)

        # 替换用户名路径
        old_username = self.path_mappings.get('username', {}).get('old', '')
        new_username = self.path_mappings.get('username', {}).get('new', '')

        if old_username and new_username and old_username != new_username:
            # 反斜杠分隔
            text = text.replace(f'\\{old_username}\\', f'\\{new_username}\\')
            # 正斜杠分隔
            text = text.replace(f'/{old_username}/', f'/{new_username}/')
            # 双反斜杠分隔（JSON 转义）
            text = text.replace(f'\\\\{old_username}\\\\', f'\\\\{new_username}\\\\')

        return text

    def restore(self, conflict_strategy='merge', progress_callback=None):
        """
        执行恢复。

        参数:
            conflict_strategy: 'merge'（跳过已有的）/ 'overwrite'（覆盖）/ 'skip'（跳过）
            progress_callback: 回调函数 callback(progress_percent, message)

        返回:
            dict: {success, report_path, path_mappings, report}
        """
        def progress(pct, msg):
            if progress_callback:
                progress_callback(pct, msg)

        # 确保包已加载
        if not self.manifest:
            self.load_package()

        progress(5, '正在检测环境...')
        self.detect_environment()

        self.report.append(('info', f'源用户: {self.path_mappings["username"]["old"]}'))
        self.report.append(('info', f'目标用户: {self.path_mappings["username"]["new"]}'))
        self.report.append(('info', f'源 Python: {self.path_mappings["python"]["old"]}'))
        self.report.append(('info', f'目标 Python: {self.path_mappings["python"]["new"]}'))

        # 确保 .cc-switch 目录存在
        os.makedirs(self.cc_switch_dir, exist_ok=True)

        # 1. 恢复 skills 文件
        progress(15, '正在恢复 Skills 文件...')
        self._restore_skills(conflict_strategy)

        # 2. 恢复 settings.json
        progress(25, '正在恢复 settings.json...')
        self._restore_settings(conflict_strategy)

        # 3. 合并数据库
        progress(40, '正在合并数据库...')
        self._merge_database(conflict_strategy)

        # 4. 恢复 MCP 服务器文件
        progress(55, '正在恢复 MCP 服务器文件...')
        self._restore_mcp_servers(conflict_strategy)

        # 5. 恢复配置文件
        progress(70, '正在恢复配置文件...')
        self._restore_configs()

        # 6. 创建符号链接
        progress(85, '正在创建符号链接...')
        self._create_symlinks()

        # 7. 运行健康检查
        progress(90, '正在运行健康检查...')
        checker = HealthChecker()
        health_results = checker.check_restore_health(self.path_mappings)
        for status, message in health_results:
            self.report.append((status, message))

        # 8. 生成 HTML 报告
        progress(95, '正在生成报告...')
        report_path = self._generate_report()

        progress(100, '恢复完成!')

        return {
            'success': True,
            'report_path': report_path,
            'path_mappings': self.path_mappings,
            'report': self.report,
        }

    def _restore_skills(self, conflict_strategy):
        """恢复 skills 目录文件，根据 conflict_strategy 处理冲突。"""
        src_skills = os.path.join(self.temp_dir, 'skills')
        dst_skills = os.path.join(self.cc_switch_dir, 'skills')

        if not os.path.isdir(src_skills):
            self.report.append(('warn', '备份包中没有 Skills 目录'))
            return

        os.makedirs(dst_skills, exist_ok=True)

        count = 0
        skipped = 0
        for item in os.listdir(src_skills):
            src_path = os.path.join(src_skills, item)
            dst_path = os.path.join(dst_skills, item)

            if not os.path.isdir(src_path):
                continue

            if os.path.exists(dst_path):
                if conflict_strategy in ('skip', 'merge'):
                    skipped += 1
                    continue
                elif conflict_strategy == 'overwrite':
                    shutil.rmtree(dst_path, ignore_errors=True)

            shutil.copytree(src_path, dst_path)
            count += 1

        self.report.append(('ok', f'Skills 恢复完成: 新增 {count} 个, 跳过 {skipped} 个'))

    def _restore_settings(self, conflict_strategy):
        """恢复 settings.json。"""
        src_settings = os.path.join(self.temp_dir, 'settings.json')
        dst_settings = os.path.join(self.cc_switch_dir, 'settings.json')

        if not os.path.exists(src_settings):
            self.report.append(('warn', '备份包中没有 settings.json'))
            return

        if os.path.exists(dst_settings):
            if conflict_strategy in ('skip', 'merge'):
                self.report.append(('info', 'settings.json 已存在，跳过'))
                return
            elif conflict_strategy == 'overwrite':
                pass  # 继续覆盖

        shutil.copy2(src_settings, dst_settings)
        self.report.append(('ok', 'settings.json 恢复完成'))

    def _merge_database(self, conflict_strategy):
        """
        合并数据库：
        - 先备份现有数据库到 ~/.cc-switch/backups/
        - 遍历 database_export 中的每个表，根据 conflict_strategy 合并记录
        - 对每条记录中的字符串值应用 _adapt_paths
        - 如果目标数据库不存在，需要先创建表结构
        """
        db_path = os.path.join(self.cc_switch_dir, 'cc-switch.db')
        backups_dir = os.path.join(self.cc_switch_dir, 'backups')

        # 备份现有数据库
        if os.path.exists(db_path):
            os.makedirs(backups_dir, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_db = os.path.join(backups_dir, f'cc-switch_{timestamp}.db')
            shutil.copy2(db_path, backup_db)
            self.report.append(('info', f'已备份现有数据库到: {backup_db}'))

        if not self.db_export:
            self.report.append(('warn', '没有数据库导出数据'))
            return

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        for table_name, pk in TABLE_PRIMARY_KEYS.items():
            if table_name not in self.db_export:
                continue

            records = self.db_export[table_name]
            if not records:
                continue

            # 收集所有列名
            all_columns = []
            seen_cols = set()
            for record in records:
                for col in record.keys():
                    if col not in seen_cols:
                        seen_cols.add(col)
                        all_columns.append(col)

            # 创建表（如果不存在）
            if table_name in REAL_TABLE_DDLS:
                cursor.execute(REAL_TABLE_DDLS[table_name])
            else:
                # 动态创建表
                col_defs = []
                for col in all_columns:
                    if col == pk:
                        col_defs.append(f'"{col}" TEXT PRIMARY KEY')
                    else:
                        col_defs.append(f'"{col}" TEXT')
                ddl = f'CREATE TABLE IF NOT EXISTS "{table_name}" ({", ".join(col_defs)})'
                cursor.execute(ddl)

            # 为已存在的表添加缺失列
            cursor.execute(f'PRAGMA table_info("{table_name}")')
            existing_cols = {row[1] for row in cursor.fetchall()}
            for col in all_columns:
                if col not in existing_cols:
                    try:
                        cursor.execute(
                            f'ALTER TABLE "{table_name}" ADD COLUMN "{col}" TEXT'
                        )
                    except sqlite3.OperationalError:
                        pass

            # 合并记录
            merged_count = 0
            skipped_count = 0
            error_count = 0

            for record in records:
                # 对字符串值应用路径适配
                adapted_record = {}
                for k, v in record.items():
                    if isinstance(v, str):
                        adapted_record[k] = self._adapt_paths(v)
                    else:
                        adapted_record[k] = v

                pk_value = adapted_record.get(pk)
                if pk_value is None:
                    error_count += 1
                    continue

                # 检查记录是否已存在
                cursor.execute(
                    f'SELECT 1 FROM "{table_name}" WHERE "{pk}" = ?', (pk_value,)
                )
                exists = cursor.fetchone()

                if exists:
                    if conflict_strategy in ('skip', 'merge'):
                        skipped_count += 1
                        continue
                    elif conflict_strategy == 'overwrite':
                        cursor.execute(
                            f'DELETE FROM "{table_name}" WHERE "{pk}" = ?',
                            (pk_value,)
                        )

                # 插入记录
                columns = [c for c in all_columns if c in adapted_record]
                placeholders = ','.join('?' * len(columns))
                col_str = ','.join(f'"{c}"' for c in columns)
                try:
                    cursor.execute(
                        f'INSERT INTO "{table_name}" ({col_str}) VALUES ({placeholders})',
                        [adapted_record[c] for c in columns]
                    )
                    merged_count += 1
                except sqlite3.IntegrityError:
                    skipped_count += 1
                except sqlite3.OperationalError as e:
                    error_count += 1
                    self.report.append((
                        'warn',
                        f'插入记录失败 ({table_name}/{pk_value}): {e}'
                    ))

            self.report.append((
                'info',
                f'表 {table_name}: 合并 {merged_count} 条, '
                f'跳过 {skipped_count} 条, 错误 {error_count} 条'
            ))

        conn.commit()
        conn.close()
        self.report.append(('ok', '数据库合并完成'))

    def _restore_mcp_servers(self, conflict_strategy):
        """恢复 .claude/mcp-servers/ 目录。"""
        src_mcp = os.path.join(self.temp_dir, 'mcp-servers')
        dst_mcp = os.path.join(self.home, '.claude', 'mcp-servers')

        if not os.path.isdir(src_mcp):
            self.report.append(('warn', '备份包中没有 mcp-servers 目录'))
            return

        os.makedirs(dst_mcp, exist_ok=True)

        count = 0
        skipped = 0
        for item in os.listdir(src_mcp):
            src_path = os.path.join(src_mcp, item)
            dst_path = os.path.join(dst_mcp, item)

            if os.path.exists(dst_path):
                if conflict_strategy in ('skip', 'merge'):
                    skipped += 1
                    continue
                elif conflict_strategy == 'overwrite':
                    if os.path.isdir(dst_path):
                        shutil.rmtree(dst_path, ignore_errors=True)
                    else:
                        os.remove(dst_path)

            if os.path.isdir(src_path):
                shutil.copytree(src_path, dst_path)
            else:
                shutil.copy2(src_path, dst_path)
            count += 1

        self.report.append((
            'ok',
            f'MCP 服务器文件恢复完成: 新增 {count} 个, 跳过 {skipped} 个'
        ))

    def _restore_configs(self):
        """
        恢复配置文件：
        - Claude Code (.claude.json): 合并 mcpServers，已有的不覆盖
        - Codex (config.toml): 如不存在则恢复，存在则跳过
        - OpenCode (opencode.json): 直接覆盖
        对所有配置文件内容应用 _adapt_paths。
        """
        # --- Claude Code (.claude.json) ---
        src_claude = os.path.join(self.temp_dir, 'claude.json')
        dst_claude = os.path.join(self.home, '.claude.json')

        if os.path.exists(src_claude):
            with open(src_claude, 'r', encoding='utf-8') as f:
                src_content = f.read()
            # 应用路径适配
            src_content = self._adapt_paths(src_content)
            try:
                src_config = json.loads(src_content)
            except json.JSONDecodeError:
                src_config = {}

            if os.path.exists(dst_claude):
                with open(dst_claude, 'r', encoding='utf-8') as f:
                    dst_config = json.load(f)

                # 合并 mcpServers — 已有的不覆盖
                src_mcp = src_config.get('mcpServers', {})
                dst_mcp = dst_config.get('mcpServers', {})

                added = 0
                for name, config in src_mcp.items():
                    if name not in dst_mcp:
                        dst_mcp[name] = config
                        added += 1
                        self.report.append((
                            'info', f'合并 MCP 服务器到 Claude Code: {name}'
                        ))
                    else:
                        self.report.append((
                            'info', f'跳过已存在的 Claude Code MCP: {name}'
                        ))

                dst_config['mcpServers'] = dst_mcp

                with open(dst_claude, 'w', encoding='utf-8') as f:
                    json.dump(dst_config, f, ensure_ascii=False, indent=2)
                self.report.append((
                    'ok', f'Claude Code 配置合并完成 (新增 {added} 个 MCP)'
                ))
            else:
                with open(dst_claude, 'w', encoding='utf-8') as f:
                    json.dump(src_config, f, ensure_ascii=False, indent=2)
                self.report.append(('ok', 'Claude Code 配置恢复完成'))
        else:
            self.report.append(('warn', '备份包中没有 claude.json'))

        # --- Codex (config.toml) ---
        src_codex = os.path.join(self.temp_dir, 'codex_config.toml')
        dst_codex_dir = os.path.join(self.home, '.codex')
        dst_codex = os.path.join(dst_codex_dir, 'config.toml')

        if os.path.exists(src_codex):
            if os.path.exists(dst_codex):
                self.report.append((
                    'warn', 'Codex config.toml 已存在，跳过（TOML 不易合并）'
                ))
            else:
                os.makedirs(dst_codex_dir, exist_ok=True)
                with open(src_codex, 'r', encoding='utf-8') as f:
                    content = f.read()
                content = self._adapt_paths(content)
                with open(dst_codex, 'w', encoding='utf-8') as f:
                    f.write(content)
                self.report.append(('ok', 'Codex 配置恢复完成'))
        else:
            self.report.append(('warn', '备份包中没有 codex_config.toml'))

        # --- OpenCode (opencode.json) ---
        src_opencode = os.path.join(self.temp_dir, 'opencode.json')
        dst_opencode_dir = os.path.join(self.home, '.config', 'opencode')
        dst_opencode = os.path.join(dst_opencode_dir, 'opencode.json')

        if os.path.exists(src_opencode):
            os.makedirs(dst_opencode_dir, exist_ok=True)
            with open(src_opencode, 'r', encoding='utf-8') as f:
                content = f.read()
            content = self._adapt_paths(content)
            with open(dst_opencode, 'w', encoding='utf-8') as f:
                f.write(content)
            self.report.append(('ok', 'OpenCode 配置恢复完成'))
        else:
            self.report.append(('warn', '备份包中没有 opencode.json'))

    def _create_symlinks(self):
        """
        为 .claude/skills, .codex/skills, .config/opencode/skills 创建
        指向 ~/.cc-switch/skills/ 的符号链接。
        已存在的链接跳过。
        """
        skills_dir = os.path.join(self.cc_switch_dir, 'skills')

        if not os.path.isdir(skills_dir):
            self.report.append(('warn', 'Skills 目录不存在，无法创建符号链接'))
            return

        link_targets = [
            os.path.join(self.home, '.claude', 'skills'),
            os.path.join(self.home, '.codex', 'skills'),
            os.path.join(self.home, '.config', 'opencode', 'skills'),
        ]

        for target in link_targets:
            target_parent = os.path.dirname(target)
            os.makedirs(target_parent, exist_ok=True)

            # 已存在的链接跳过
            if os.path.islink(target):
                self.report.append(('info', f'符号链接已存在: {target}'))
                continue
            if os.path.exists(target):
                self.report.append((
                    'info', f'目录已存在（非符号链接），跳过: {target}'
                ))
                continue

            try:
                os.symlink(skills_dir, target, target_is_directory=True)
                self.report.append((
                    'ok', f'创建符号链接: {target} -> {skills_dir}'
                ))
            except OSError as e:
                # 尝试使用 Junction 作为回退（不需要管理员权限）
                try:
                    subprocess.run(
                        f'mklink /J "{target}" "{skills_dir}"',
                        shell=True, check=True, capture_output=True
                    )
                    self.report.append((
                        'ok', f'创建目录联接(Junction): {target} -> {skills_dir}'
                    ))
                except Exception:
                    self.report.append((
                        'warn',
                        f'创建符号链接失败（可能需要管理员权限）: {target} - {e}'
                    ))

    def _generate_report(self):
        """
        生成 HTML 报告：
        - 摘要：成功/警告/错误数量
        - 环境检测：已安装工具状态
        - 路径变更对照表（旧→新）
        - 详细日志（所有 report 项）
        - 后续步骤建议
        保存到 ~/.cc-switch/migration-report.html
        用 webbrowser.open 在浏览器中打开。
        返回报告文件路径。
        """
        # 统计状态
        ok_count = sum(1 for s, _ in self.report if s == 'ok')
        warn_count = sum(1 for s, _ in self.report if s == 'warn')
        error_count = sum(1 for s, _ in self.report if s == 'error')
        info_count = sum(1 for s, _ in self.report if s == 'info')

        # 构建 HTML
        html_parts = []
        html_parts.append('<!DOCTYPE html>')
        html_parts.append('<html lang="zh-CN">')
        html_parts.append('<head>')
        html_parts.append('<meta charset="UTF-8">')
        html_parts.append('<title>CC Switch 迁移报告</title>')
        html_parts.append('<style>')
        html_parts.append(
            'body { font-family: "Microsoft YaHei", Arial, sans-serif; '
            'margin: 20px; background: #f5f5f5; }'
        )
        html_parts.append(
            '.container { max-width: 900px; margin: 0 auto; background: white; '
            'padding: 30px; border-radius: 8px; '
            'box-shadow: 0 2px 4px rgba(0,0,0,0.1); }'
        )
        html_parts.append(
            'h1 { color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 10px; }'
        )
        html_parts.append('h2 { color: #555; margin-top: 30px; }')
        html_parts.append(
            '.summary { display: flex; gap: 15px; margin: 20px 0; flex-wrap: wrap; }'
        )
        html_parts.append(
            '.stat { padding: 15px 25px; border-radius: 8px; color: white; '
            'font-size: 18px; font-weight: bold; }'
        )
        html_parts.append('.stat-ok { background: #4CAF50; }')
        html_parts.append('.stat-warn { background: #FF9800; }')
        html_parts.append('.stat-error { background: #F44336; }')
        html_parts.append('.stat-info { background: #2196F3; }')
        html_parts.append(
            'table { width: 100%; border-collapse: collapse; margin: 15px 0; }'
        )
        html_parts.append(
            'th, td { border: 1px solid #ddd; padding: 10px; text-align: left; }'
        )
        html_parts.append('th { background: #f8f8f8; }')
        html_parts.append(
            '.log-entry { padding: 8px 15px; margin: 4px 0; border-radius: 4px; '
            'font-size: 14px; }'
        )
        html_parts.append(
            '.log-ok { background: #e8f5e9; border-left: 4px solid #4CAF50; }'
        )
        html_parts.append(
            '.log-warn { background: #fff3e0; border-left: 4px solid #FF9800; }'
        )
        html_parts.append(
            '.log-error { background: #ffebee; border-left: 4px solid #F44336; }'
        )
        html_parts.append(
            '.log-info { background: #e3f2fd; border-left: 4px solid #2196F3; }'
        )
        html_parts.append(
            '.suggestions { background: #f0f4c3; padding: 15px; '
            'border-radius: 8px; margin-top: 20px; }'
        )
        html_parts.append('</style>')
        html_parts.append('</head>')
        html_parts.append('<body>')
        html_parts.append('<div class="container">')

        # 标题
        html_parts.append('<h1>CC Switch 迁移报告</h1>')
        html_parts.append(
            f'<p>生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>'
        )

        # 摘要
        html_parts.append('<h2>摘要</h2>')
        html_parts.append('<div class="summary">')
        html_parts.append(f'<div class="stat stat-ok">成功: {ok_count}</div>')
        html_parts.append(f'<div class="stat stat-info">信息: {info_count}</div>')
        html_parts.append(f'<div class="stat stat-warn">警告: {warn_count}</div>')
        html_parts.append(f'<div class="stat stat-error">错误: {error_count}</div>')
        html_parts.append('</div>')

        # 环境检测
        html_parts.append('<h2>环境检测</h2>')
        html_parts.append('<table>')
        html_parts.append('<tr><th>工具</th><th>状态</th></tr>')
        tools = self.path_mappings.get('tools', {})
        for tool, installed in tools.items():
            status = '已安装' if installed else '未安装'
            color = '#4CAF50' if installed else '#F44336'
            html_parts.append(
                f'<tr><td>{tool}</td>'
                f'<td style="color: {color}; font-weight: bold;">{status}</td></tr>'
            )
        html_parts.append('</table>')

        # 路径变更对照
        html_parts.append('<h2>路径变更对照</h2>')
        html_parts.append('<table>')
        html_parts.append('<tr><th>类型</th><th>旧值</th><th>新值</th></tr>')

        python_map = self.path_mappings.get('python', {})
        old_py = python_map.get('old', 'N/A') or 'N/A'
        new_py = python_map.get('new', 'N/A') or 'N/A'
        html_parts.append(
            f'<tr><td>Python 路径</td><td>{old_py}</td><td>{new_py}</td></tr>'
        )

        username_map = self.path_mappings.get('username', {})
        old_user = username_map.get('old', 'N/A') or 'N/A'
        new_user = username_map.get('new', 'N/A') or 'N/A'
        html_parts.append(
            f'<tr><td>用户名</td><td>{old_user}</td><td>{new_user}</td></tr>'
        )

        html_parts.append('</table>')

        # 详细日志
        html_parts.append('<h2>详细日志</h2>')
        for status, message in self.report:
            html_parts.append(
                f'<div class="log-entry log-{status}">'
                f'[{status.upper()}] {message}</div>'
            )

        # 后续步骤建议
        html_parts.append('<div class="suggestions">')
        html_parts.append('<h3>后续步骤建议</h3>')
        html_parts.append('<ul>')
        if error_count > 0:
            html_parts.append(
                '<li><strong>有错误发生</strong>，请检查错误日志并手动修复</li>'
            )
        html_parts.append(
            '<li>验证 Claude Code、Codex、OpenCode 是否能正常识别 skills 和 MCP 服务器</li>'
        )
        html_parts.append(
            '<li>如有符号链接创建失败，请以<strong>管理员权限</strong>重新运行迁移工具</li>'
        )
        html_parts.append('<li>检查 API 密钥是否正确配置（providers 表中的 api_key）</li>')
        html_parts.append('<li>重启 CC Switch 及相关工具使配置生效</li>')
        html_parts.append(
            '<li>如 node_repl MCP 未迁移，请在安装 Codex 后由其自动生成</li>'
        )
        html_parts.append('</ul>')
        html_parts.append('</div>')

        html_parts.append('</div>')
        html_parts.append('</body>')
        html_parts.append('</html>')

        html_content = '\n'.join(html_parts)

        # 保存报告
        os.makedirs(self.cc_switch_dir, exist_ok=True)
        report_path = os.path.join(self.cc_switch_dir, 'migration-report.html')
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        # 在浏览器中打开
        report_url = f'file:///{report_path.replace(os.sep, "/")}'
        try:
            webbrowser.open(report_url)
        except Exception:
            pass

        self.report.append(('info', f'报告已保存到: {report_path}'))

        return report_path

    def cleanup(self):
        """清理临时目录。"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            self.temp_dir = None
