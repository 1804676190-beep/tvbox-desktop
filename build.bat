@echo off
chcp 65001 >nul
echo ========================================
echo   TVBox Desktop — Windows 一键打包
echo ========================================
echo.

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

:: 检查 mpv
where mpv >nul 2>&1
if errorlevel 1 (
    echo [提示] 未找到 mpv，播放功能可能不可用
    echo 请从 https://mpv.io/ 下载 mpv 并将 mpv-2.dll 放到项目目录
    echo.
)

:: 安装依赖
echo [1/3] 安装依赖...
pip install -r requirements.txt pyinstaller -q
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)

:: 打包
echo [2/3] 正在打包...
pyinstaller tvbox.spec --clean --noconfirm
if errorlevel 1 (
    echo [错误] 打包失败
    pause
    exit /b 1
)

:: 复制 mpv-2.dll
echo [3/3] 复制 mpv-2.dll...
if exist "mpv-2.dll" (
    copy /Y "mpv-2.dll" "dist\TVBox Desktop\mpv-2.dll" >nul
    echo   已复制 mpv-2.dll
) else (
    echo   [警告] 未找到 mpv-2.dll，请手动复制到 dist\TVBox Desktop\ 目录
)

echo.
echo ========================================
echo   打包完成！
echo   输出目录: dist\TVBox Desktop\
echo   可执行文件: dist\TVBox Desktop\TVBox Desktop.exe
echo ========================================
echo.
pause
