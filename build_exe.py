"""打包脚本：用 PyInstaller 把影藏 PolyFlix 打包成桌面 exe。

用法：
    python build_exe.py

输出：
    dist/PolyFlix/PolyFlix.exe  （--onedir 模式，整个文件夹即可分发）

首次打包需 1-3 分钟，之后再打会快些。
"""
import subprocess
import sys
import os

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--name", "PolyFlix",
    "--onedir",          # 目录模式，启动快（比 --onefile 快很多）
    "--windowed",        # 无控制台黑窗，纯桌面应用
    "--icon", "static/polyflix-favicon.ico",  # exe 图标
    # 静态文件 & 模板 & 版本号打进 exe
    "--add-data", f"static{os.pathsep}static",
    "--add-data", f"templates{os.pathsep}templates",
    "--add-data", f"VERSION{os.pathsep}VERSION",
    # uvicorn 动态导入的子模块（PyInstaller 扫不到）
    "--hidden-import", "uvicorn.logging",
    "--hidden-import", "uvicorn.protocols.http.auto",
    "--hidden-import", "uvicorn.protocols.http.h11_impl",
    "--hidden-import", "uvicorn.protocols.websockets.auto",
    "--hidden-import", "uvicorn.protocols.websockets.wsproto_impl",
    "--hidden-import", "uvicorn.lifespan.on",
    "--hidden-import", "uvicorn.lifespan.off",
    # py7zr / pyzipper
    "--hidden-import", "py7zr",
    "--hidden-import", "pyzipper",
    # pywebview Windows 后端
    "--hidden-import", "webview",
    "--hidden-import", "webview.platforms.edgechromium",
    "--hidden-import", "webview.platforms.winforms",
    # 排除不需要的大模块，减小体积
    "--exclude-module", "tkinter",
    "--exclude-module", "matplotlib",
    "--exclude-module", "numpy",
    "--exclude-module", "PIL",
    "--exclude-module", "PyQt5",
    "--exclude-module", "PyQt6",
    "--exclude-module", "PySide6",
    # 入口
    "main.py",
]

print("正在打包，请稍候…\n")
print(">", " ".join(cmd), "\n")
ret = subprocess.run(cmd)
if ret.returncode == 0:
    print("\n[OK] 打包完成！")
    print("    输出目录：dist/PolyFlix/")
    print("    双击 dist/PolyFlix/PolyFlix.exe 即可运行")
else:
    print("\n[FAIL] 打包失败，请看上方日志")
    sys.exit(1)
