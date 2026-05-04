@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: =============================================
::   TVBox Desktop — 一键安装脚本 (Windows)
:: =============================================

title TVBox Desktop 安装向导
color 0A

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║     📺 TVBox Desktop — 一键安装脚本     ║
echo  ╚══════════════════════════════════════════╝
echo.

:: -----------------------------------------
::  1. 检查 Python
:: -----------------------------------------
echo  [1/5] 检查 Python 环境...

python --version >nul 2>&1
if errorlevel 1 (
    echo  ❌ 未找到 Python！
    echo.
    echo  正在尝试自动安装 Python 3.12...
    echo.

    :: 尝试用 winget 安装
    winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements >nul 2>&1
    if errorlevel 1 (
        :: winget 不可用，用 choco
        choco install python312 -y >nul 2>&1
        if errorlevel 1 (
            echo  ⚠️ 自动安装失败，请手动安装 Python 3.10+
            echo  下载地址: https://www.python.org/downloads/
            echo  安装时请勾选 "Add Python to PATH"
            pause
            exit /b 1
        )
    )

    :: 刷新 PATH
    set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Python\Python312\;%LOCALAPPDATA%\Programs\Python\Python312\Scripts\"

    python --version >nul 2>&1
    if errorlevel 1 (
        echo  ❌ Python 安装后仍无法使用，请重启终端后重试
        pause
        exit /b 1
    )
    echo  ✅ Python 安装成功
) else (
    for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
    echo  ✅ Python !PYVER! 已安装
)

:: 检查 Python 版本 >= 3.10
python -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo  ❌ Python 版本过低，需要 3.10+
    pause
    exit /b 1
)

:: -----------------------------------------
::  2. 升级 pip
:: -----------------------------------------
echo.
echo  [2/5] 升级 pip...
python -m pip install --upgrade pip -q >nul 2>&1
echo  ✅ pip 已更新

:: -----------------------------------------
::  3. 安装 Python 依赖
:: -----------------------------------------
echo.
echo  [3/5] 安装 Python 依赖...

:: 获取脚本所在目录
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

pip install -r requirements.txt -q
if errorlevel 1 (
    echo  ❌ 依赖安装失败，尝试使用国内镜像...
    pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple -q
    if errorlevel 1 (
        echo  ❌ 依赖安装失败，请检查网络连接
        pause
        exit /b 1
    )
)
echo  ✅ Python 依赖安装完成

:: -----------------------------------------
::  4. 安装 mpv 播放器
:: -----------------------------------------
echo.
echo  [4/5] 检查 mpv 播放器...

set "MPV_INSTALLED=0"

:: 检查 mpv 是否已安装
where mpv >nul 2>&1
if not errorlevel 1 (
    set "MPV_INSTALLED=1"
    echo  ✅ mpv 已安装
)

:: 检查 mpv-2.dll 是否在当前目录
if exist "%SCRIPT_DIR%mpv-2.dll" (
    set "MPV_INSTALLED=1"
    echo  ✅ mpv-2.dll 已存在
)

if "!MPV_INSTALLED!"=="0" (
    echo  ⏳ 正在下载 mpv...

    :: 尝试用 winget 安装
    winget install mpv.mpv --silent --accept-package-agreements --accept-source-agreements >nul 2>&1
    if not errorlevel 1 (
        echo  ✅ mpv 安装成功
        set "MPV_INSTALLED=1"
    )

    if "!MPV_INSTALLED!"=="0" (
        :: 尝试用 choco 安装
        choco install mpv -y >nul 2>&1
        if not errorlevel 1 (
            echo  ✅ mpv 安装成功
            set "MPV_INSTALLED=1"
        )
    )

    if "!MPV_INSTALLED!"=="0" (
        echo  ⚠️ 自动安装 mpv 失败
        echo.
        echo  请手动安装 mpv：
        echo    方法1: winget install mpv.mpv
        echo    方法2: choco install mpv
        echo    方法3: 从 https://mpv.io/ 下载，将 mpv-2.dll 放到:
        echo           %SCRIPT_DIR%
        echo.
        echo  没有 mpv 也可以运行程序，但播放功能不可用
        echo.
    )
)

:: -----------------------------------------
::  5. 创建快捷方式
:: -----------------------------------------
echo.
echo  [5/5] 创建桌面快捷方式...

set "SHORTCUT_SCRIPT=%SCRIPT_DIR%create_shortcut.vbs"

> "!SHORTCUT_SCRIPT!" (
    echo Set oWS = WScript.CreateObject^("WScript.Shell"^)
    echo Set oLink = oWS.CreateShortcut^(oWS.SpecialFolders^("Desktop"^) ^& "\TVBox Desktop.lnk"^)
    echo oLink.TargetPath = "%SCRIPT_DIR%main.py"
    echo oLink.WorkingDirectory = "%SCRIPT_DIR%"
    echo oLink.Description = "TVBox Desktop 播放器"
    echo oLink.WindowStyle = 1
    echo oLink.Save
)

cscript //nologo "!SHORTCUT_SCRIPT!" >nul 2>&1
if errorlevel 1 (
    echo  ⚠️ 快捷方式创建失败（不影响使用）
) else (
    echo  ✅ 桌面快捷方式已创建
    del "!SHORTCUT_SCRIPT!" >nul 2>&1
)

:: -----------------------------------------
::  完成
:: -----------------------------------------
echo.
echo  ╔══════════════════════════════════════════╗
echo  ║           ✅ 安装完成！                  ║
echo  ╠══════════════════════════════════════════╣
echo  ║                                          ║
echo  ║  启动方式:                               ║
echo  ║    双击桌面快捷方式                       ║
echo  ║    或运行: python main.py                 ║
echo  ║                                          ║
echo  ║  打包为 EXE:                             ║
echo  ║    运行: build.bat                        ║
echo  ║                                          ║
echo  ╚══════════════════════════════════════════╝
echo.

:: 询问是否立即启动
set /p "LAUNCH=是否立即启动 TVBox Desktop? (Y/N): "
if /i "!LAUNCH!"=="Y" (
    echo.
    echo  🚀 启动中...
    start "" python "%SCRIPT_DIR%main.py"
)

pause
