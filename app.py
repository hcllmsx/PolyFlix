"""
影藏 PolyFlix —— 把文件藏进一段能正常播放的 MP4 视频里

后端：FastAPI
- 标准无密码 ZIP  → zipfile（标准库）
- 带密码 ZIP      → pyzipper（AES-256）
- 7z（带/不带密码）→ py7zr（纯 Python）
- 大文件流式上传 + 流式响应，内存占用恒定
"""

import os
import sys
import json
import time
import shutil
import tempfile
import zipfile
import traceback
import logging
from datetime import datetime
import uuid
from urllib.parse import quote

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from pyzipper import AESZipFile, WZ_AES  # AES 加密 ZIP
import py7zr                     # 7z 支持

app = FastAPI(title="影藏 PolyFlix")

# 兼容 PyInstaller 打包：源码运行用脚本目录，打包后用 _MEIPASS（解压目录）
BASE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
_STATIC_DIR = os.path.join(BASE_DIR, "static")
_TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

# 流式读写块大小：8MB（内存占用恒定，不随文件大小增长）
CHUNK_SIZE = 8 * 1024 * 1024

# 保存最近的构建结果，供 /api/download 下载（构建与下载分离，避免浏览器把大文件读进内存）
_builds: dict = {}
_MAX_BUILDS = 3

# 压缩方式映射 → (zipfile 压缩类型, compresslevel / 7z preset)
# 对照 WinRAR：存储/最快/较快/标准/较好/最好
_COMP_MAP = {
    "store":    {"zip": (zipfile.ZIP_STORED, None),   "preset": None},      # 存储，最快
    "fastest":  {"zip": (zipfile.ZIP_DEFLATED, 1),  "preset": 1},         # 最快
    "fast":     {"zip": (zipfile.ZIP_DEFLATED, 3),  "preset": 3},         # 较快
    "normal":   {"zip": (zipfile.ZIP_DEFLATED, 6),  "preset": 5},         # 标准
    "good":     {"zip": (zipfile.ZIP_DEFLATED, 7),  "preset": 7},         # 较好
    "best":     {"zip": (zipfile.ZIP_DEFLATED, 9),  "preset": 9},         # 最好
}

# 7z 的 preset 映射
_7Z_PRESET = {"fastest": 1, "fast": 3, "normal": 5, "good": 7, "best": 9}


def zip_comp_kwargs(method: str) -> dict:
    """返回用于 zipfile.ZipFile / pyzipper.AESZipFile 的 compression + compresslevel 关键字参数。"""
    comp, level = _COMP_MAP.get(method, _COMP_MAP["normal"])["zip"]
    kw = {"compression": comp}
    if level is not None:
        kw["compresslevel"] = level
    return kw


def fmt_bytes(n: int) -> str:
    """把字节数格式化成人类可读。"""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} TB"

# --------------------------------------------------------------------------- #
# 日志：既打到控制台，也存内存，供前端 /api/log 拉取
# --------------------------------------------------------------------------- #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("polyflix")

_debug_log: list[dict] = []


def log(msg: str, level: str = "info"):
    entry = {"t": time.strftime("%H:%M:%S"), "level": level, "msg": msg}
    _debug_log.append(entry)
    if len(_debug_log) > 300:
        _debug_log.pop(0)
    getattr(logger, level, logger.info)(msg)


# 读取 VERSION 文件（单一真相源，dev 和打包后都从这里取）
def _read_version() -> str:
    try:
        with open(os.path.join(BASE_DIR, "VERSION"), "r", encoding="utf-8") as f:
            return f.read().strip() or "unknown"
    except Exception:
        return "unknown"


APP_VERSION = _read_version()


# --------------------------------------------------------------------------- #
# 页面
# --------------------------------------------------------------------------- #
@app.get("/")
async def index():
    return FileResponse(
        os.path.join(_TEMPLATES_DIR, "index.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/favicon.ico")
async def favicon():
    return FileResponse(
        os.path.join(_STATIC_DIR, "polyflix-favicon.ico"),
        media_type="image/x-icon",
    )


@app.get("/api/version")
async def version():
    return {"version": APP_VERSION}


@app.get("/api/log")
async def get_log():
    return {"log": _debug_log}


@app.post("/api/log/clear")
async def clear_log():
    _debug_log.clear()
    return {"status": "ok"}


# --------------------------------------------------------------------------- #
# 构建辅助函数
# --------------------------------------------------------------------------- #
def build_inner_archive(hidden_dir: str, cfg: dict, out_path: str):
    """根据配置创建内层压缩包到 out_path。"""
    fmt = cfg.get("innerArchive", "none")
    password = cfg.get("innerPassword", "") or None
    method = cfg.get("compression", "normal")
    names = os.listdir(hidden_dir)
    log(f"内层压缩: 格式={fmt}, 方式={method}, 带密码={bool(password)}, 文件数={len(names)}")

    if fmt == "7z":
        if method == "store":
            filters = [{"id": py7zr.FILTER_COPY}]
        else:
            filters = [{"id": py7zr.FILTER_LZMA2, "preset": _7Z_PRESET.get(method, 5)}]
        with py7zr.SevenZipFile(out_path, "w", password=password, filters=filters) as z:
            for n in names:
                z.write(os.path.join(hidden_dir, n), n)
        log(f"  7z 完成: {os.path.getsize(out_path)} 字节")
    elif fmt == "zip":
        kw = zip_comp_kwargs(method)
        if password:
            with AESZipFile(out_path, "w", encryption=WZ_AES, **kw) as z:
                z.setpassword(password.encode())
                for n in names:
                    z.write(os.path.join(hidden_dir, n), n)
        else:
            with zipfile.ZipFile(out_path, "w", **kw) as z:
                for n in names:
                    z.write(os.path.join(hidden_dir, n), n)
        log(f"  内层 ZIP 完成: {os.path.getsize(out_path)} 字节")
    else:
        raise ValueError(f"未知的内层格式: {fmt}")


def split_into_volumes(filepath: str, volume_size: int, name_base: str, ext: str):
    """
    把单个文件切成分卷：name_base.ext.001, name_base.ext.002, ...
    7-Zip 能直接打开 .001 并自动拼接后续分卷。
    返回 [(arcname, vol_path), ...]
    """
    volumes = []
    index = 1
    src_dir = os.path.dirname(filepath)
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(volume_size)
            if not chunk:
                break
            vol_name = f"{name_base}.{ext}.{index:03d}"
            vol_path = os.path.join(src_dir, vol_name)
            with open(vol_path, "wb") as vf:
                vf.write(chunk)
            volumes.append((vol_name, vol_path))
            index += 1
    if not volumes:
        # 空文件也至少产出一个分卷
        vol_name = f"{name_base}.{ext}.001"
        vol_path = os.path.join(src_dir, vol_name)
        open(vol_path, "wb").close()
        volumes.append((vol_name, vol_path))
    log(f"  分卷完成: {len(volumes)} 个，每卷 ≤ {volume_size} 字节")
    return volumes


def build_outer_zip(entries, password: str, out_path: str, method: str = "normal"):
    """entries: List[(arcname, filepath)]"""
    kw = zip_comp_kwargs(method)
    log(f"外层 ZIP: 条目数={len(entries)}, 带密码={bool(password)}, 方式={method}")
    if password:
        with AESZipFile(out_path, "w", encryption=WZ_AES, **kw) as z:
            z.setpassword(password.encode())
            for arcname, fpath in entries:
                z.write(fpath, arcname)
    else:
        with zipfile.ZipFile(out_path, "w", **kw) as z:
            for arcname, fpath in entries:
                z.write(fpath, arcname)
    log(f"  外层 ZIP 完成: {os.path.getsize(out_path)} 字节")


def save_upload_to_file(upload: UploadFile, dest: str):
    """流式把上传文件写到磁盘，避免一次性读进内存。"""
    upload.file.seek(0)
    with open(dest, "wb") as f:
        shutil.copyfileobj(upload.file, f, length=CHUNK_SIZE)
    upload.file.close()


# --------------------------------------------------------------------------- #
# 核心接口：构建伪装文件（sync，FastAPI 自动放进线程池，不阻塞事件循环）
# --------------------------------------------------------------------------- #
@app.post("/api/build")
def build(
    mp4: UploadFile = File(...),
    hidden_files: list[UploadFile] = File(...),
    config: str = Form(...),
):
    tmpdir = tempfile.mkdtemp()
    try:
        log(f"========== 收到构建请求 ==========")
        log(f"MP4: filename={mp4.filename!r}")
        log(f"隐藏文件数: {len(hidden_files)}")
        for i, hf in enumerate(hidden_files):
            log(f"  [{i}] {hf.filename!r}")
        log(f"config 原始字符串: {config!r}")

        cfg = json.loads(config)
        log(f"config 解析: {cfg}")

        # 1) 流式保存 MP4 到磁盘（不读进内存）
        mp4_path = os.path.join(tmpdir, "cover.mp4")
        save_upload_to_file(mp4, mp4_path)
        mp4_size = os.path.getsize(mp4_path)
        log(f"MP4 保存完成: {mp4_size} 字节")

        if mp4_size == 0:
            return JSONResponse({"error": "未收到 MP4 文件"}, status_code=400)
        if not hidden_files:
            return JSONResponse({"error": "未收到要隐藏的文件"}, status_code=400)

        # 2) 流式保存隐藏文件到临时目录
        hidden_dir = os.path.join(tmpdir, "hidden")
        os.makedirs(hidden_dir)
        for hf in hidden_files:
            safe = os.path.basename(hf.filename or "file")
            dest = os.path.join(hidden_dir, safe)
            save_upload_to_file(hf, dest)
            log(f"  写入临时文件: {safe} ({os.path.getsize(dest)} 字节)")

        # 磁盘空间检查（需要约源文件总大小 ×2 的空间：上传原件 + 外层 ZIP）
        method = cfg.get("compression", "normal")
        total_source = mp4_size + sum(
            os.path.getsize(os.path.join(hidden_dir, n)) for n in os.listdir(hidden_dir)
        )
        disk = shutil.disk_usage(tmpdir)
        need = total_source * 2 if method != "store" else int(total_source * 1.1) + 1024 * 1024
        if disk.free < need:
            log(f"⚠️ 磁盘空间不足: 剩余 {fmt_bytes(disk.free)}, 约需 {fmt_bytes(need)}", level="warning")
        else:
            log(f"磁盘空间: 剩余 {fmt_bytes(disk.free)}（约需 {fmt_bytes(need)}）")

        # 3) 决定外层 ZIP 里放什么
        timestamp = datetime.now().strftime("%H%M%S")
        if cfg.get("innerArchive", "none") == "none":
            entries = [(n, os.path.join(hidden_dir, n)) for n in os.listdir(hidden_dir)]
            log(f"无内层，直接把 {len(entries)} 个文件放入外层 ZIP")
        else:
            ext = "7z" if cfg["innerArchive"] == "7z" else "zip"
            inner_filename = f"polyflix-{timestamp}.{ext}"
            inner_path = os.path.join(tmpdir, inner_filename)
            build_inner_archive(hidden_dir, cfg, inner_path)

            # 分卷
            if cfg.get("splitVolume", False) and int(cfg.get("splitSizeMB", 0) or 0) > 0:
                volume_size = int(cfg["splitSizeMB"]) * 1024 * 1024
                entries = split_into_volumes(inner_path, volume_size, f"polyflix-{timestamp}", ext)
                log(f"内层已分卷: {[e[0] for e in entries]}")
            else:
                entries = [(inner_filename, inner_path)]
                log(f"内层压缩包: {inner_filename}")

        # 4) 创建外层 ZIP
        outer_path = os.path.join(tmpdir, "outer.zip")
        build_outer_zip(entries, cfg.get("outerPassword", ""), outer_path, method)
        zip_size = os.path.getsize(outer_path)

        total_size = mp4_size + zip_size
        log(f"拼接: MP4({mp4_size}) + ZIP({zip_size}) = {total_size} 字节")

        # 派生下载文件名
        mp4_name = os.path.basename(mp4.filename or "video.mp4")
        base = mp4_name[:-4] if mp4_name.lower().endswith(".mp4") else mp4_name
        download_name = f"{base}-polyflix.mp4"
        log(f"下载文件名: {download_name}")

        # 5) 清理隐藏文件（已在外层 ZIP 里），保留 mp4 + outer.zip 供下载
        shutil.rmtree(hidden_dir, True)

        # 6) 存储构建结果，返回下载链接（构建与下载分离，浏览器原生下载流式写盘）
        download_id = uuid.uuid4().hex[:12]
        if len(_builds) >= _MAX_BUILDS:
            oldest_id = next(iter(_builds))
            old = _builds.pop(oldest_id)
            shutil.rmtree(old["tmpdir"], True)
        _builds[download_id] = {
            "mp4_path": mp4_path,
            "zip_path": outer_path,
            "filename": download_name,
            "size": total_size,
            "tmpdir": tmpdir,
        }

        log(f"下载 ID: {download_id}")
        log(f"========== 构建成功 ==========")
        return JSONResponse({
            "downloadUrl": f"/api/download/{download_id}",
            "filename": download_name,
            "size": total_size,
        })

    except Exception as e:
        tb = traceback.format_exc()
        log(f"!!!!! 构建失败 !!!!!", level="error")
        log(tb, level="error")
        log(f"错误: {type(e).__name__}: {e}", level="error")
        shutil.rmtree(tmpdir, True)
        return JSONResponse(
            {"error": f"{type(e).__name__}: {e}", "traceback": tb},
            status_code=500,
        )


# --------------------------------------------------------------------------- #
# 下载接口：流式输出 MP4 + ZIP 拼接结果（浏览器原生下载，直接写盘）
# --------------------------------------------------------------------------- #
@app.get("/api/download/{download_id}")
def download(download_id: str):
    if download_id not in _builds:
        return JSONResponse({"error": "下载链接已失效，请重新构建"}, status_code=404)
    info = _builds[download_id]

    def generate():
        with open(info["mp4_path"], "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk
        with open(info["zip_path"], "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(
        generate(),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(info['filename'])}",
            "Content-Length": str(info["size"]),
        },
    )


# --------------------------------------------------------------------------- #
# 直接运行：python app.py
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=18181)
