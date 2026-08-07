# CC Switch 迁移工具

轻量级桌面工具，实现 CC Switch 的 Skills、MCP Servers、API Providers 从一台电脑一键迁移到另一台电脑。

## 功能概览

- **一键备份**：将 CC Switch 的 Skills、MCP Servers、API Providers 及相关配置打包为 `.zip` 迁移包
- **一键恢复**：在新电脑上从迁移包恢复，自动适配 Python 路径和用户名，创建符号链接
- **选择性迁移**：勾选需要的项目进行迁移，灵活控制迁移范围
- **健康检查**：备份前自动检查环境完整性，恢复后生成 HTML 报告

## 截图

工具采用深色主题，左侧导航栏 + 右侧内容区布局，风格与 CC Switch 保持一致。

## 环境要求

- Windows 10/11（64 位）
- Python 3.8+
- 已安装 CC Switch（[GitHub](https://github.com/farion1231/cc-switch)）
- 建议已安装 Claude Code / Codex / OpenCode 中的至少一个

## 快速开始

### 方式一：直接运行 Python 脚本

```bash
# 1. 安装依赖
pip install customtkinter

# 2. 运行
python cc_migrator.py
```

### 方式二：打包为 EXE（免 Python 环境运行）

```bash
# 1. 安装打包依赖
pip install customtkinter pyinstaller

# 2. 执行打包
build_exe.bat

# 3. 打包结果在 dist/CC-Switch-Migrator/ 目录
#    将整个文件夹复制到目标电脑即可使用
```

## 使用指南

### 在旧电脑上备份

1. 打开工具，点击左侧导航栏「备份」
2. 查看健康检查结果，确保环境和数据库正常
3. 点击「开始备份」
4. 迁移包 `.zip` 文件将自动保存到桌面

### 在新电脑上恢复

1. 将迁移包 `.zip` 复制到新电脑
2. 打开工具，点击左侧导航栏「恢复」
3. 点击「浏览」选择迁移包
4. 查看环境检测和路径映射信息
5. 选择冲突处理策略：
   - **合并（推荐）**：跳过已有项，只添加新项
   - **覆盖**：用迁移包内容替换所有
   - **跳过**：只恢复不存在的项
6. 建议先关闭 CC Switch 应用，再点击「开始恢复」
7. 恢复完成后将自动打开 HTML 迁移报告

### 选择性迁移

1. 点击左侧导航栏「选择性迁移」
2. 勾选需要迁移的 Skills、MCP Servers、API Providers
3. 点击「备份选中项」

## 迁移包内容

| 内容 | 说明 |
|:---|:---|
| `database_export.json` | CC Switch 数据库导出（Skills、MCPs、Providers、Settings） |
| `skills/` | Skills 文件目录（含 SKILL.md 等文件） |
| `settings.json` | CC Switch 设置文件 |
| `mcp-servers/` | Claude Code MCP 服务器文件 |
| `claude.json` | Claude Code 配置文件 |
| `codex_config.toml` | Codex 配置文件 |
| `opencode.json` | OpenCode 配置文件 |
| `manifest.json` | 迁移包元数据（版本、时间、路径依赖等） |
| `restore.bat` | 基础恢复脚本（可选，无需 Python） |

## 恢复时自动处理

- **Python 路径适配**：自动将旧电脑的 Python 路径替换为新电脑的路径
- **用户名路径适配**：自动替换用户名相关的路径
- **符号链接创建**：为 Claude Code、Codex、OpenCode 创建指向 `~/.cc-switch/skills/` 的符号链接
- **数据库合并**：智能合并数据库记录，支持三种冲突策略
- **配置文件合并**：Claude Code 的 MCP 配置采用合并模式，已有的不覆盖
- **数据库备份**：恢复前自动备份现有数据库到 `~/.cc-switch/backups/`

## 安全说明

> **重要：迁移包包含 API 密钥等敏感信息！**

- 迁移包中的 `database_export.json` 和配置文件包含 API 密钥、登录凭据等敏感信息
- **请勿将迁移包上传到公开仓库或分享给他人**
- 本工具的源代码不包含任何硬编码的密钥或凭据
- 本工具不会收集、上传或传输任何用户数据到第三方服务器
- 所有操作均在本地完成，迁移包仅保存在用户桌面

## 项目结构

```
cc-switch-migrator/
├── cc_migrator.py           # GUI 主程序（CustomTkinter）
├── cc_migrator_core.py      # 核心模块（路径检测、健康检查、备份/恢复引擎）
├── requirements.txt         # Python 依赖
├── build_exe.bat            # PyInstaller 打包脚本
├── CC-Switch-Migrator.spec  # PyInstaller 配置文件
└── .gitignore
```

## 技术栈

- **GUI 框架**：CustomTkinter（基于 Tkinter 的现代化深色主题 UI 库）
- **核心逻辑**：纯 Python 标准库（sqlite3、json、zipfile、shutil、os、ctypes 等）
- **打包工具**：PyInstaller
- **字体**：楷体（KaiTi），匹配 CC Switch 界面风格

## 常见问题

### Q: 恢复后符号链接创建失败怎么办？

符号链接创建需要管理员权限。请以管理员身份运行工具，或手动执行：
```cmd
mklink /J "%USERPROFILE%\.claude\skills" "%USERPROFILE%\.cc-switch\skills"
mklink /J "%USERPROFILE%\.codex\skills" "%USERPROFILE%\.cc-switch\skills"
mklink /J "%USERPROFILE%\.config\opencode\skills" "%USERPROFILE%\.cc-switch\skills"
```

### Q: 迁移后 MCP 服务器不工作？

检查 MCP 配置中的 Python 路径是否已正确适配。如果 MCP 依赖本地路径的脚本文件，需要手动确认文件在新电脑上存在。

### Q: 可以跨平台迁移吗（Windows → Mac/Linux）？

当前版本仅支持 Windows。路径适配逻辑基于 Windows 路径格式（盘符、反斜杠）。

## 许可证

MIT License
