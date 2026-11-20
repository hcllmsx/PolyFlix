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
import webbrowser

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
                item = {"path": p, "name": os.path.basename(p), "size": os.path.getsize(p)}
                # 标记影藏产物：前端据此在双视频模式下拦截（文件隐藏模式下允许套娃）
                try:
                    if is_polyflix_product(p):
                        item["isProduct"] = True
                except Exception:
                    pass
                files.append(item)
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


# ---------------------------------------------------------------------------
# exe 模式拖放：pywebview 的 DOM 事件能拿到被拖入文件的真实本地路径
# （webview 原生 drop 事件的 File 对象没有 .path，无法用于本地构建），
# 因此在这里注册 drop 监听，复用与 select_* 一致的产物校验逻辑，
# 再把结果用 evaluate_js 桥接回前端的 window.__polyflixOnDropped。
# ---------------------------------------------------------------------------
def _describe_dropped_mp4(path):
    """单文件（MP4 外壳）：复用与 select_mp4 一致的产品拦截逻辑。"""
    try:
        if is_polyflix_product(path):
            return {"error": "polyflix_product", "name": os.path.basename(path)}
        return {"files": [{"path": path, "name": os.path.basename(path),
                           "size": os.path.getsize(path)}]}
    except Exception as e:
        log(f"拖放解析 MP4 出错: {e}", level="error")
        return {"error": "read_error", "name": os.path.basename(path)}


def _describe_dropped_hidden(paths):
    """多文件（隐藏内容）：复用与 select_hidden_files 一致的产物标记逻辑。"""
    files = []
    for p in paths:
        try:
            item = {"path": p, "name": os.path.basename(p), "size": os.path.getsize(p)}
            try:
                if is_polyflix_product(p):
                    item["isProduct"] = True
            except Exception:
                pass
            files.append(item)
        except Exception as e:
            log(f"跳过无法读取的路径 {p!r}: {e}", level="warning")
    return {"files": files}


def handle_dom_drop(event, kind):
    try:
        files_meta = (event.get("dataTransfer") or {}).get("files", [])
        paths = [f["pywebviewFullPath"] for f in files_meta if f.get("pywebviewFullPath")]
        if not paths:
            return
        if kind == "mp4":
            result = _describe_dropped_mp4(paths[0])
        else:
            result = _describe_dropped_hidden(paths)
        webview.windows[0].evaluate_js(
            "window.__polyflixOnDropped(" + json.dumps(result, ensure_ascii=False) + f", '{kind}')"
        )
    except Exception as ex:
        log(f"处理拖放事件出错: {ex}", level="error")


def register_dom_drop_handlers():
    """窗口页面加载完成后注册 exe 拖放监听（此时 DOM 元素已存在）。"""
    if getattr(register_dom_drop_handlers, "_registered", False):
        return
    register_dom_drop_handlers._registered = True
    try:
        win = webview.windows[0]
        win.dom.get_element("#dz-mp4").events.drop += lambda e: handle_dom_drop(e, "mp4")
        win.dom.get_element("#dz-hidden").events.drop += lambda e: handle_dom_drop(e, "hidden")
        log("已注册 exe 拖放处理（真实本地路径）")
    except Exception as e:
        log(f"注册 exe 拖放处理失败: {e}", level="error")
        register_dom_drop_handlers._registered = False  # 允许下次重试


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


WEBVIEW2_DOWNLOAD_URL = "https://developer.microsoft.com/zh-cn/microsoft-edge/webview2/#download-section"
DOTNET_DOWNLOAD_URL = "https://dotnet.microsoft.com/zh-cn/download/dotnet-framework"
_WEBVIEW2_MIN_VERSION = (86, 0, 622, 0)
_WEBVIEW2_CLIENT_GUIDS = (
    "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",  # WebView2 Runtime
    "{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}",  # Edge Beta
    "{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}",  # Edge Dev
    "{65C35B14-6C1D-4122-AC46-7148CC9D6497}",  # Edge Canary
)


def _parse_version_tuple(ver_str):
    try:
        parts = [int(p) for p in str(ver_str).strip().split(".")]
        while len(parts) < 4:
            parts.append(0)
        return tuple(parts[:4])
    except Exception:
        return (0, 0, 0, 0)


def check_webview2_runtime():
    """检测 Windows 下 WebView2 所需的运行环境（与 pywebview 的判定口径一致）。

    返回 (ok, reason)：
    - (True, "")          环境就绪
    - (False, "dotnet")   缺少 .NET Framework 4.6.2+
    - (False, "webview2") 缺少 Microsoft Edge WebView2 Runtime（或版本过低）
    """
    if sys.platform != "win32":
        return True, ""

    import winreg

    # 1. 检查 .NET Framework 4.6.2+（Release >= 394802）
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full",
        ) as key:
            release, _ = winreg.QueryValueEx(key, "Release")
            if int(release) < 394802:
                return False, "dotnet"
    except Exception:
        return False, "dotnet"

    # 2. 检查 WebView2 Runtime（兼容 64 位 / 32 位 / 当前用户安装路径）
    reg_locations = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeUpdate\Clients"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\EdgeUpdate\Clients"),
    )
    for guid in _WEBVIEW2_CLIENT_GUIDS:
        for root, base_path in reg_locations:
            try:
                with winreg.OpenKey(root, rf"{base_path}\{guid}") as key:
                    pv, _ = winreg.QueryValueEx(key, "pv")
                    if pv and _parse_version_tuple(pv) >= _WEBVIEW2_MIN_VERSION:
                        return True, ""
            except Exception:
                continue

    return False, "webview2"


def show_missing_runtime_dialog(reason):
    """使用 Windows 原生弹窗提示缺少 WebView2 / .NET 环境，避免静默降级到 IE11。"""
    if reason == "dotnet":
        url = DOTNET_DOWNLOAD_URL
        msg = (
            "未检测到 .NET Framework 4.6.2 及以上版本，无法加载现代渲染内核（WebView2）。\n\n"
            "请先安装 .NET Framework 4.6.2+，安装完成后重新启动影藏 PolyFlix。\n\n"
            "是否立即打开微软官方下载页面？"
        )
    else:
        url = WEBVIEW2_DOWNLOAD_URL
        msg = (
            "未检测到 Microsoft Edge WebView2 Runtime（或版本过低）。\n\n"
            "缺少该组件会导致界面样式错乱、背景变白且功能异常，因此已阻止启动。\n"
            "请安装微软官方的「WebView2 运行时（常青独立安装程序）」，安装完成后重新打开影藏 PolyFlix。\n\n"
            "是否立即打开微软官方下载页面？"
        )

    title = "影藏 PolyFlix - 缺少运行环境"
    if sys.platform == "win32":
        import ctypes
        MB_YESNO = 0x00000004
        MB_ICONWARNING = 0x00000030
        MB_SETFOREGROUND = 0x00010000
        IDYES = 6
        res = ctypes.windll.user32.MessageBoxW(
            None, msg, title, MB_YESNO | MB_ICONWARNING | MB_SETFOREGROUND
        )
        if res == IDYES:
            webbrowser.open(url)
    else:
        print(f"{title}\n{msg}\n{url}", flush=True)


def main():
    # 启动前检测 WebView2 运行环境，避免缺失时被 pywebview 静默降级到 IE11
    ok, reason = check_webview2_runtime()
    if not ok:
        show_missing_runtime_dialog(reason)
        sys.exit(1)

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
    # 页面加载完成后注册 exe 拖放监听（能拿到真实本地路径）
    webview.windows[0].events.loaded += register_dom_drop_handlers
    if sys.platform == "win32":
        webview.start(gui="edgechromium")
    else:
        webview.start()
    # 窗口关闭 → webview.start() 返回 → 清理临时构建文件 → 进程退出
    cleanup_builds()


if __name__ == "__main__":
    main()
