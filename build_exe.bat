@echo off
chcp 65001 >nul
echo ========================================
echo   CC Switch 迁移工具 - 打包脚本
echo ========================================
echo.

REM 检查 Python
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

REM 安装依赖
echo [1/3] 安装依赖...
pip install customtkinter pyinstaller -q
if %ERRORLEVEL% neq 0 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)

REM 打包
echo [2/3] 开始打包...
pyinstaller --noconfirm --onedir --windowed ^
    --name "CC-Switch-Migrator" ^
    --add-data "cc_migrator_core.py;." ^
    --hidden-import customtkinter ^
    --collect-all customtkinter ^
    cc_migrator.py

if %ERRORLEVEL% neq 0 (
    echo [错误] 打包失败
    pause
    exit /b 1
)

echo [3/3] 打包完成!
echo.
echo 可执行文件位于: dist\CC-Switch-Migrator\CC-Switch-Migrator.exe
echo.
echo 将整个 dist\CC-Switch-Migrator 文件夹复制到目标电脑即可使用。
echo.
pause
