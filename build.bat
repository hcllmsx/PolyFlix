@echo off
chcp 65001 >nul 2>nul
title 打包影藏 PolyFlix

echo ============================================
echo   影藏 PolyFlix - 打包成 exe
echo ============================================
echo.

rem ---- 选一个能用的 Python 解释器（和 run.bat 同逻辑）----
set "PYEXE="
if exist ".venv\Scripts\python.exe" set "PYEXE=.venv\Scripts\python.exe"
if not defined PYEXE if exist ".venv\bin\python.exe" set "PYEXE=.venv\bin\python.exe"
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
echo 正在安装/更新依赖（含 pyinstaller、pywebview）...
%PYEXE% -m pip install -r requirements.txt -q

echo.
echo 开始打包（约 20 秒）...
echo.

%PYEXE% build_exe.py
if errorlevel 1 (
    echo.
    echo [失败] 打包出错，请看上方日志
    pause
    exit /b 1
)

echo.
echo ============================================
echo   打包完成！
echo   便携版文件夹：dist\PolyFlix\
echo   双击 dist\PolyFlix\PolyFlix.exe 即可运行
echo ============================================
echo.

set /p DOZIP="是否压缩成 zip 方便分发？(y/n): "
if /i "%DOZIP%"=="y" (
    echo 正在压缩...
    powershell -NoProfile -Command "Compress-Archive -Path 'dist\PolyFlix\*' -DestinationPath 'dist\PolyFlix-portable.zip' -Force"
    if exist "dist\PolyFlix-portable.zip" (
        echo.
        echo 压缩完成：dist\PolyFlix-portable.zip
        echo 可以直接把这个 zip 文件发给别人。
    ) else (
        echo 压缩失败。
    )
)

echo.
pause
