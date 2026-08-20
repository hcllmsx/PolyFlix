"""影藏 PolyFlix —— 桌面窗口入口

后台线程运行 FastAPI（uvicorn），主线程用 pywebview 打开原生窗口。
关闭窗口即退出整个程序。

源码运行：  python main.py
打包后运行：双击 PolyFlix.exe
"""
import sys
import os
import time
import json
import threading
import urllib.request
import shutil

import uvicorn
import webview

from app import app, _builds, log, do_build, POLYFLIX_TEMP_DIR, fmt_bytes, is_polyflix_product

PORT = 18181
HOST = "127.0.0.1"

# 流式拷贝块大小（与 app.py 一致）
CHUNK_SIZE = 8 * 1024 * 1024


class JsApi:
    """JS ↔ Python 桥接。

    exe（pywebview）模式下：
    - 文件选择走原生对话框（拿本地路径，不走 HTTP 上传）
    - 构建走本地路径直读（绕过 WebView2 大文件上传限制）
    - 下载 / 日志导出走原生保存对话框
    """

    # ---- 文件选择 ----
    def select_mp4(self):
        """弹原生文件对话框选单个 MP4，返回 {path, name, size} 或 null。"""
        try:
            result = webview.windows[0].create_file_dialog(
                webview.OPEN_DIALOG,
                file_types=("MP4 Video (*.mp4)", "All files (*.*)"),
            )
        except Exception as e:
            log(f"选择 MP4 出错: {e}", level="error")
            return None
        if not result:
            return None
        # pywebview 可能返回 str / list / tuple，统一取第一个
        if isinstance(result, (list, tuple)):
            if len(result) == 0:
                return None
            path = result[0]
        else:
            path = result
        if not path:
            return None
        try:
            # 检测是否是 PolyFlix 产物（MP4 + ZIP 拼接），拒绝当封面
            if is_polyflix_product(path):
                log(f"拒绝选择 PolyFlix 产物作为封面: {path}")
                return {"error": "polyflix_product", "name": os.path.basename(path)}
            return {"path": path, "name": os.path.basename(path), "size": os.path.getsize(path)}
        except Exception as e:
            log(f"解析 MP4 路径出错: {e}", level="error")
            return None

    def select_hidden_files(self):
        """弹原生文件对话框选多个文件，返回 [{path, name, size}, ...] 或 null。"""
        try:
            result = webview.windows[0].create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=True,
            )
        except Exception as e:
            log(f"选择文件出错: {e}", level="error")
            return None
        if not result:
            return None
        # pywebview 多选时返回 list 或 tuple
        if isinstance(result, (list, tuple)):
            paths = list(result)
        else:
            paths = [result]
        if not paths:
            return None
        files = []
        for p in paths:
            if not p:
                continue
            try:
                files.append({"path": p, "name": os.path.basename(p), "size": os.path.getsize(p)})
            except Exception as e:
                log(f"跳过无法读取的路径 {p!r}: {e}", level="warning")
        return files if files else None

    # ---- 构建（从本地路径直读，不走 HTTP 上传）----
    def start_build(self, mp4_path, hidden_paths_json, config_json, mp4_display_name="video.mp4"):
        """同步构建（可能耗时几分钟）。JS 端 await 这个调用，同时轮询 /api/log 显示进度。"""
        try:
            hidden_paths = json.loads(hidden_paths_json)
            cfg = json.loads(config_json)
            result = do_build(mp4_path, hidden_paths, cfg, mp4_display_name)
            return {"ok": True, **result}
        except Exception as e:
            log(f"构建错误: {type(e).__name__}: {e}", level="error")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ---- 下载 ----
    def pick_save_path(self, download_id, default_name):
        """只弹原生保存对话框，返回 {path} 或 {cancelled} 或 {error}。
        与 write_download 分离，让前端能在用户选完路径后立即切换提示为"正在保存…"。
        """
        if not download_id or download_id not in _builds:
            log(f"下载失败: ID={download_id!r} 不存在或已失效", level="error")
            return {"ok": False, "error": "下载链接已失效，请重新构建"}

        info = _builds[download_id]
        log(f"pywebview 保存对话框: filename={info['filename']}, size={info['size']}")

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

        dest = result if isinstance(result, str) else result[0]
        return {"ok": True, "path": dest}

    def write_download(self, download_id, dest_path):
        """把构建产物（mp4 + zip 拼接）写到指定路径。可能耗时较长（大文件）。"""
        if not download_id or download_id not in _builds:
            return {"ok": False, "error": "下载链接已失效，请重新构建"}
        if not dest_path:
            return {"ok": False, "error": "保存路径为空"}

        info = _builds[download_id]
        log(f"开始写入伪装文件: {dest_path} ({fmt_bytes(info['size'])})")

        try:
            with open(dest_path, "wb") as out:
                # 产物 = mp4 + 尾部部分（ZIP 模式 = outer.zip；双视频模式 = free box）
                for src_path in (info["mp4_path"], info["tail_path"]):
                    with open(src_path, "rb") as src:
                        shutil.copyfileobj(src, out, length=CHUNK_SIZE)
            log(f"保存完成: {dest_path}")
            return {"ok": True, "path": dest_path, "size": info["size"]}
        except Exception as e:
            log(f"写入文件失败: {e}", level="error")
            return {"ok": False, "error": f"写入文件失败: {e}"}

    # ---- 日志导出 ----
    def pick_text_save_path(self, default_name):
        """只弹保存对话框，返回路径。"""
        try:
            result = webview.windows[0].create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=default_name,
                file_types=("Text files (*.txt)", "All files (*.*)"),
            )
        except Exception as e:
            log(f"导出出错: {e}", level="error")
            return {"ok": False, "error": f"导出出错: {e}"}

        if not result:
            return {"ok": False, "cancelled": True}

        dest = result if isinstance(result, str) else result[0]
        return {"ok": True, "path": dest}

    def write_text_file(self, dest_path, content):
        """把文本内容写到指定路径。"""
        if not dest_path:
            return {"ok": False, "error": "保存路径为空"}
        try:
            with open(dest_path, "w", encoding="utf-8") as f:
                f.write(content)
            return {"ok": True, "path": dest_path}
        except Exception as e:
            return {"ok": False, "error": f"写入失败: {e}"}


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


def cleanup_builds():
    """退出前清理所有残留的临时构建目录（可能几个 GB）。
    优先一次性删掉整个 PolyFlix 统一缓存目录（含本次运行 + 历史崩溃残留）；
    失败再退回到逐个清 _builds 里记录的。
    """
    if POLYFLIX_TEMP_DIR and os.path.isdir(POLYFLIX_TEMP_DIR):
        try:
            shutil.rmtree(POLYFLIX_TEMP_DIR, True)
            print(f"[PolyFlix] 已清理缓存目录: {POLYFLIX_TEMP_DIR}", flush=True)
            _builds.clear()
            return
        except Exception as e:
            print(f"[PolyFlix] 清理缓存目录失败: {e}", flush=True)
    # 退回：逐个清 _builds 里记录的
    for bid, info in list(_builds.items()):
        try:
            shutil.rmtree(info.get("tmpdir", ""), True)
        except Exception:
            pass
    _builds.clear()


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
        js_api=JsApi(),    # 注入 JS 桥接
    )
    webview.start()
    # 窗口关闭 → webview.start() 返回 → 清理临时构建文件 → 进程退出
    cleanup_builds()


if __name__ == "__main__":
    main()
