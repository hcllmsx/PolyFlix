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
import shutil

import uvicorn
import webview

from app import app, _builds, log

PORT = 18181
HOST = "127.0.0.1"

# 流式拷贝块大小（与 app.py 一致）
CHUNK_SIZE = 8 * 1024 * 1024


class JsApi:
    """JS ↔ Python 桥接：打包后的 exe 里浏览器原生下载不可靠，
    用 pywebview 的原生保存对话框替代。"""

    def save_download(self, download_id):
        """弹出原生保存对话框，把构建产物（mp4 + zip 拼接）写到用户选定的路径。"""
        if not download_id or download_id not in _builds:
            log(f"下载失败: ID={download_id!r} 不存在或已失效", level="error")
            return {"ok": False, "error": "下载链接已失效，请重新构建"}

        info = _builds[download_id]
        log(f"pywebview 保存对话框: filename={info['filename']}, size={info['size']}")

        # 弹出保存对话框（pywebview 的方法可在任意线程调用）
        try:
            result = webview.windows[0].create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=info["filename"],
                file_types=("MP4 Video (*.mp4)", "All files (*.*)"),
            )
        except Exception as e:
            log(f"保存对话框出错: {e}", level="error")
            return {"ok": False, "error": f"保存对话框出错: {e}"}

        if not result:
            log("用户取消了保存")
            return {"ok": False, "cancelled": True}

        # pywebview 返回 str 或 list[str]，统一取第一个
        dest = result if isinstance(result, str) else result[0]
        log(f"开始写入伪装文件: {dest}")

        try:
            with open(dest, "wb") as out:
                for src_path in (info["mp4_path"], info["zip_path"]):
                    with open(src_path, "rb") as src:
                        shutil.copyfileobj(src, out, length=CHUNK_SIZE)
            log(f"保存完成: {dest}")
            return {"ok": True, "path": dest, "size": info["size"]}
        except Exception as e:
            log(f"写入文件失败: {e}", level="error")
            return {"ok": False, "error": f"写入文件失败: {e}"}


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
        maximized=True,    # 启动即最大化（用户仍可手动还原）
        js_api=JsApi(),    # 注入 JS 桥接：原生保存对话框处理下载
    )
    webview.start()
    # 窗口关闭 → webview.start() 返回 → main() 结束 → daemon 线程自动终止 → 进程退出


if __name__ == "__main__":
    main()
