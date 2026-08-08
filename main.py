"""影藏 PolyFlix —— 桌面窗口入口

后台线程运行 FastAPI（uvicorn），主线程用 pywebview 打开原生窗口。
关闭窗口即退出整个程序。

源码运行：  python main.py
打包后运行：双击 PolyFlix.exe
"""
import sys
import time
import threading
import urllib.request

import uvicorn
import webview

from app import app

PORT = 18181
HOST = "127.0.0.1"


def wait_for_server(timeout=15):
    """轮询 /api/health 直到服务器就绪或超时。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://{HOST}:{PORT}/api/health", timeout=1):
                return True
        except Exception:
            time.sleep(0.2)
    return False


def run_server():
    """后台线程运行 FastAPI（禁用信号处理，兼容非主线程）。"""
    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # 非主线程不能装信号处理
    server.run()


def main():
    # 启动后端服务（守护线程，主进程退出时自动结束）
    t = threading.Thread(target=run_server, daemon=True)
    t.start()

    if not wait_for_server():
        print("服务器启动失败，请检查端口 18181 是否被占用。")
        input("按回车键退出…")
        sys.exit(1)

    # 主线程打开原生窗口（阻塞，关闭窗口后返回）
    webview.create_window(
        "影藏 PolyFlix",
        f"http://{HOST}:{PORT}",
        width=1280,
        height=900,
        min_size=(900, 600),
    )
    webview.start()
    # 窗口关闭 → webview.start() 返回 → main() 结束 → daemon 线程自动终止 → 进程退出


if __name__ == "__main__":
    main()
