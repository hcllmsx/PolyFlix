@echo off
chcp 65001 >nul 2>nul
title 影藏 PolyFlix

echo ============================================
echo   影藏 PolyFlix
echo   把秘密藏进一段能正常播放的视频里
echo ============================================
echo.

rem ---- 选一个能用的 Python 解释器 ----
rem 优先用项目里的 .venv（如果存在且能用），避免污染系统 Python
rem 注意：不用 activate.bat（它在文件夹改名后路径会失效），直接用全路径调用 python.exe
set "PYEXE="
if exist ".venv\Scripts\python.exe" set "PYEXE=.venv\Scripts\python.exe"
if not defined PYEXE if exist ".venv\bin\python.exe" set "PYEXE=.venv\bin\python.exe"

rem 没有 venv 就用系统 Python（优先 py 启动器）
if not defined PYEXE (
    where py >nul 2>nul && set "PYEXE=py"
)
if not defined PYEXE (
    where python >nul 2>nul && set "PYEXE=python"
)
if not defined PYEXE (
    echo [错误] 未找到 Python。请先安装 Python 3.8+：
    echo        https://www.python.org/downloads/
    echo        安装时勾选 "Add Python to PATH"。
    echo.
    pause
    exit /b 1
)

echo 使用 Python: %PYEXE%
echo.
echo 正在检查依赖（首次运行需一点时间）...
%PYEXE% -m pip install -r requirements.txt -q

echo.
echo 启动服务...
echo 浏览器将打开 http://127.0.0.1:18181
echo 按 Ctrl+C 停止服务
echo.

rem 清理可能残留的旧进程（占用 18181 端口的）
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":18181" ^| findstr "LISTENING"') do (
    if not "%%a"=="0" (
        echo 检测到端口 18181 被旧进程 PID %%a 占用，正在清理...
        taskkill /PID %%a /F >nul 2>nul
    )
)

rem 延迟 3 秒再开浏览器，等服务真的起来
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://127.0.0.1:18181'"

%PYEXE% -m uvicorn app:app --host 127.0.0.1 --port 18181

echo.
echo 服务已停止。
pause
