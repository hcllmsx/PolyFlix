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
import threading
import atexit
from datetime import datetime
import uuid
from urllib.parse import quote

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

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

# --------------------------------------------------------------------------- #
# 统一缓存目录：所有临时文件都放在 %TEMP%/PolyFlix 下，避免散落在系统 Temp 根目录
# 这样软件退出时可以一次性删掉整个 PolyFlix 目录，用户也可以手动清理而不影响其他软件
# --------------------------------------------------------------------------- #
try:
    POLYFLIX_TEMP_DIR = os.path.join(tempfile.gettempdir(), "PolyFlix")
    os.makedirs(POLYFLIX_TEMP_DIR, exist_ok=True)
except Exception:
    # 极端情况（系统 Temp 不可写）退回到默认行为（散落在 Temp 根目录）
    POLYFLIX_TEMP_DIR = None

# 当前正在使用的临时目录（构建中或待下载），手动清理缓存时要跳过这些
_active_tmpdirs: set[str] = set()
_cache_lock = threading.Lock()


def _polyflix_mkdtemp():
    """在 PolyFlix 统一缓存目录下建临时目录，失败则退回系统默认。"""
    if POLYFLIX_TEMP_DIR:
        return tempfile.mkdtemp(dir=POLYFLIX_TEMP_DIR)
    return tempfile.mkdtemp()


def _dir_size(path: str) -> int:
    """递归计算目录总大小（字节）。"""
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _cleanup_on_exit():
    """进程退出时尽量清理整个 PolyFlix 缓存目录（含历史残留）。
    由 atexit 注册，正常退出 / Ctrl+C / uvicorn 退出都会触发。
    """
    if not POLYFLIX_TEMP_DIR or not os.path.isdir(POLYFLIX_TEMP_DIR):
        return
    try:
        shutil.rmtree(POLYFLIX_TEMP_DIR, True)
    except Exception:
        pass


atexit.register(_cleanup_on_exit)

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
    # 尝试多个可能的位置：
    # 1. BASE_DIR/VERSION          （dev 模式 / --add-data "VERSION;."）
    # 2. BASE_DIR/VERSION/VERSION   （--add-data "VERSION;VERSION" 的旧行为）
    for candidate in (
        os.path.join(BASE_DIR, "VERSION"),
        os.path.join(BASE_DIR, "VERSION", "VERSION"),
    ):
        try:
            if os.path.isfile(candidate):
                with open(candidate, "r", encoding="utf-8") as f:
                    return f.read().strip() or "Unknown"
        except Exception:
            continue
    return "Unknown"


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
    # 每次请求都重读 VERSION 文件，避免模块加载时读不到导致永久 "unknown"
    return {"version": _read_version()}


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
def _dedup_name(name: str, used: set[str]) -> str:
    """同名去重：file.txt → file(1).txt → file(2).txt"""
    if name not in used:
        used.add(name)
        return name
    root, dot_ext = os.path.splitext(name)
    i = 1
    while f"{root}({i}){dot_ext}" in used:
        i += 1
    result = f"{root}({i}){dot_ext}"
    used.add(result)
    return result


def _zip_write_stream(z, arcname: str, fpath: str):
    """分块写入 ZIP 条目，大文件定期打进度日志。
    仅用于标准 zipfile.ZipFile（无密码）—— pyzipper 的 AESZipFile.open() 写入模式
    对大文件不稳定（ZIP64 检测有 bug），带密码的 ZIP 必须用 z.write()。
    """
    fsize = os.path.getsize(fpath)
    big = fsize > 256 * 1024 * 1024  # 只对 >256MB 的文件打进度
    written = 0
    last_log_pct = 0
    # 始终用 ZIP64 格式，避免大文件边界问题（Python 3.11+ 支持 force_zip64）
    try:
        zf = z.open(arcname, 'w', force_zip64=True)
    except TypeError:
        # Python < 3.11 不支持 force_zip64 参数
        zf = z.open(arcname, 'w')
    with zf:
        with open(fpath, 'rb') as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                zf.write(chunk)
                written += len(chunk)
                if big and fsize > 0:
                    pct = written * 100 // fsize
                    if pct - last_log_pct >= 10:
                        log(f"    写入 {arcname}: {pct}% ({fmt_bytes(written)} / {fmt_bytes(fsize)})")
                        last_log_pct = pct


def build_inner_archive(entries, cfg: dict, out_path: str):
    """根据配置创建内层压缩包到 out_path。entries: List[(arcname, filepath)]"""
    fmt = cfg.get("innerArchive", "none")
    password = cfg.get("innerPassword", "") or None
    method = cfg.get("compression", "normal")
    log(f"内层压缩: 格式={fmt}, 方式={method}, 带密码={bool(password)}, 文件数={len(entries)}")

    if fmt == "7z":
        if method == "store":
            filters = [{"id": py7zr.FILTER_COPY}]
        else:
            filters = [{"id": py7zr.FILTER_LZMA2, "preset": _7Z_PRESET.get(method, 5)}]
        # py7zr 1.1+ 中仅传 password 不会真正加密，必须 header_encryption=True
        # （7z 加密是全局的，header_encryption 同时加密文件内容和元数据）
        zkw = {"password": password, "filters": filters}
        if password:
            zkw["header_encryption"] = True
        with py7zr.SevenZipFile(out_path, "w", **zkw) as z:
            for i, (arcname, fpath) in enumerate(entries):
                log(f"  7z [{i+1}/{len(entries)}]: {arcname} ({fmt_bytes(os.path.getsize(fpath))})")
                z.write(fpath, arcname)
        log(f"  7z 完成: {os.path.getsize(out_path)} 字节")
    elif fmt == "zip":
        kw = zip_comp_kwargs(method)
        if password:
            # AESZipFile 的流式 open() 写入大文件不稳定，用 write() 更可靠
            with AESZipFile(out_path, "w", encryption=WZ_AES, allowZip64=True, **kw) as z:
                z.setpassword(password.encode())
                for i, (arcname, fpath) in enumerate(entries):
                    log(f"  内层 ZIP [{i+1}/{len(entries)}]: {arcname} ({fmt_bytes(os.path.getsize(fpath))})")
                    z.write(fpath, arcname)
        else:
            with zipfile.ZipFile(out_path, "w", allowZip64=True, **kw) as z:
                for i, (arcname, fpath) in enumerate(entries):
                    log(f"  内层 ZIP [{i+1}/{len(entries)}]: {arcname} ({fmt_bytes(os.path.getsize(fpath))})")
                    _zip_write_stream(z, arcname, fpath)
        log(f"  内层 ZIP 完成: {os.path.getsize(out_path)} 字节")
    else:
        raise ValueError(f"未知的内层格式: {fmt}")


def split_into_volumes(filepath: str, volume_size: int, name_base: str, ext: str):
    """
    把单个文件切成分卷：name_base.ext.001, name_base.ext.002, ...
    7-Zip 能直接打开 .001 并自动拼接后续分卷。
    流式写入，内存占用恒定（不随分卷大小增长）。
    返回 [(arcname, vol_path), ...]
    """
    volumes = []
    index = 1
    src_dir = os.path.dirname(filepath)
    with open(filepath, "rb") as f:
        while True:
            vol_name = f"{name_base}.{ext}.{index:03d}"
            vol_path = os.path.join(src_dir, vol_name)
            written = 0
            empty = True
            with open(vol_path, "wb") as vf:
                while written < volume_size:
                    # 每次最多读 CHUNK_SIZE，避免把整个分卷读进内存
                    need = min(CHUNK_SIZE, volume_size - written)
                    chunk = f.read(need)
                    if not chunk:
                        break
                    vf.write(chunk)
                    written += len(chunk)
                    empty = False
            if empty:
                # 源文件已读完，当前分卷是空的 → 删掉并退出
                os.remove(vol_path)
                break
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
    """entries: List[(arcname, filepath)]。
    带密码用 z.write()（pyzipper 流式写入不稳定）；无密码用流式分块写入（有进度）。
    """
    kw = zip_comp_kwargs(method)
    total = len(entries)
    log(f"外层 ZIP: 条目数={total}, 带密码={bool(password)}, 方式={method}")
    if password:
        with AESZipFile(out_path, "w", encryption=WZ_AES, allowZip64=True, **kw) as z:
            z.setpassword(password.encode())
            for i, (arcname, fpath) in enumerate(entries):
                log(f"  外层 ZIP [{i+1}/{total}]: {arcname} ({fmt_bytes(os.path.getsize(fpath))})")
                z.write(fpath, arcname)
    else:
        with zipfile.ZipFile(out_path, "w", allowZip64=True, **kw) as z:
            for i, (arcname, fpath) in enumerate(entries):
                log(f"  外层 ZIP [{i+1}/{total}]: {arcname} ({fmt_bytes(os.path.getsize(fpath))})")
                _zip_write_stream(z, arcname, fpath)
    log(f"  外层 ZIP 完成: {os.path.getsize(out_path)} 字节")


def save_upload_to_file(upload: UploadFile, dest: str):
    """流式把上传文件写到磁盘，避免一次性读进内存。"""
    upload.file.seek(0)
    try:
        with open(dest, "wb") as f:
            shutil.copyfileobj(upload.file, f, length=CHUNK_SIZE)
    finally:
        upload.file.close()


# --------------------------------------------------------------------------- #
# 核心构建逻辑：从本地文件路径构建伪装文件（HTTP 上传和 exe 本地构建共用）
# --------------------------------------------------------------------------- #
def do_build(mp4_path: str, hidden_paths: list, cfg: dict, mp4_display_name: str = "video.mp4"):
    """
    从本地文件路径构建伪装文件。
    mp4_path: MP4 本地路径（会硬链接/复制到临时目录）
    hidden_paths: List[str] 隐藏文件本地路径（直接引用，不复制）
    cfg: 配置 dict
    mp4_display_name: 用于派生下载文件名
    返回 {"download_id", "filename", "size"}；失败抛异常
    """
    tmpdir = _polyflix_mkdtemp()
    with _cache_lock:
        _active_tmpdirs.add(tmpdir)
    try:
        log(f"========== 收到构建请求 ==========")
        log(f"MP4: {mp4_path}")
        log(f"隐藏文件数: {len(hidden_paths)}")
        for i, hp in enumerate(hidden_paths):
            log(f"  [{i}] {os.path.basename(hp)}")
        log(f"config: {cfg}")

        # 1) 把 MP4 放进临时目录（硬链接优先，省时省空间；失败则复制）
        new_mp4_path = os.path.join(tmpdir, "cover.mp4")
        try:
            os.link(mp4_path, new_mp4_path)
            log(f"MP4 硬链接完成: {os.path.getsize(new_mp4_path)} 字节")
        except OSError:
            log(f"MP4 复制中… ({fmt_bytes(os.path.getsize(mp4_path))})")
            shutil.copy2(mp4_path, new_mp4_path)
            log(f"MP4 复制完成: {os.path.getsize(new_mp4_path)} 字节")
        mp4_path = new_mp4_path
        mp4_size = os.path.getsize(mp4_path)

        if mp4_size == 0:
            raise ValueError("MP4 文件为空")
        if not hidden_paths:
            raise ValueError("没有隐藏文件")

        # 2) 构建隐藏文件条目（同名去重）
        used_names: set[str] = set()
        hidden_entries = []
        for hp in hidden_paths:
            arcname = _dedup_name(os.path.basename(hp), used_names)
            hidden_entries.append((arcname, hp))
            log(f"  隐藏文件: {arcname} ({fmt_bytes(os.path.getsize(hp))})")

        # 磁盘空间检查
        method = cfg.get("compression", "normal")
        total_source = mp4_size + sum(os.path.getsize(hp) for _, hp in hidden_entries)
        disk = shutil.disk_usage(tmpdir)
        need = total_source * 2 if method != "store" else int(total_source * 1.1) + 1024 * 1024
        if disk.free < need:
            log(f"⚠️ 磁盘空间不足: 剩余 {fmt_bytes(disk.free)}, 约需 {fmt_bytes(need)}", level="warning")
        else:
            log(f"磁盘空间: 剩余 {fmt_bytes(disk.free)}（约需 {fmt_bytes(need)}）")

        # 3) 决定外层 ZIP 里放什么
        timestamp = datetime.now().strftime("%H%M%S")
        if cfg.get("innerArchive", "none") == "none":
            entries = hidden_entries
            log(f"无内层，直接把 {len(entries)} 个文件放入外层 ZIP")
        else:
            ext = "7z" if cfg["innerArchive"] == "7z" else "zip"
            inner_filename = f"polyflix-{timestamp}.{ext}"
            inner_path = os.path.join(tmpdir, inner_filename)
            build_inner_archive(hidden_entries, cfg, inner_path)

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
        mp4_name = os.path.basename(mp4_display_name)
        base = mp4_name[:-4] if mp4_name.lower().endswith(".mp4") else mp4_name
        download_name = f"{base}-polyflix.mp4"
        log(f"下载文件名: {download_name}")

        # 5) 存储构建结果
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
        # tmpdir 现由 _builds 持有，从活动集合移除（手动清缓存时会跳过 _builds 里的）
        with _cache_lock:
            _active_tmpdirs.discard(tmpdir)
        return {"download_id": download_id, "filename": download_name, "size": total_size}

    except Exception:
        tb = traceback.format_exc()
        log(f"!!!!! 构建失败 !!!!!", level="error")
        log(tb, level="error")
        with _cache_lock:
            _active_tmpdirs.discard(tmpdir)
        shutil.rmtree(tmpdir, True)
        raise


# --------------------------------------------------------------------------- #
# HTTP 构建接口（浏览器 dev 模式）：保存上传文件后调用 do_build
# --------------------------------------------------------------------------- #
@app.post("/api/build")
def build(
    mp4: UploadFile = File(...),
    hidden_files: list[UploadFile] = File(...),
    config: str = Form(...),
):
    upload_tmp = _polyflix_mkdtemp()
    with _cache_lock:
        _active_tmpdirs.add(upload_tmp)
    try:
        # 保存 MP4 上传
        mp4_path = os.path.join(upload_tmp, "cover.mp4")
        save_upload_to_file(mp4, mp4_path)
        if os.path.getsize(mp4_path) == 0:
            return JSONResponse({"error": "未收到 MP4 文件"}, status_code=400)

        # 保存隐藏文件上传（同名去重）
        used_names: set[str] = set()
        hidden_paths = []
        for hf in hidden_files:
            safe = _dedup_name(os.path.basename(hf.filename or "file"), used_names)
            dest = os.path.join(upload_tmp, safe)
            save_upload_to_file(hf, dest)
            hidden_paths.append(dest)

        cfg = json.loads(config)
        result = do_build(mp4_path, hidden_paths, cfg, mp4.filename or "video.mp4")
        return JSONResponse({
            "downloadUrl": f"/api/download/{result['download_id']}",
            "filename": result["filename"],
            "size": result["size"],
        })
    except Exception as e:
        tb = traceback.format_exc()
        log(f"HTTP 构建错误: {type(e).__name__}: {e}", level="error")
        return JSONResponse(
            {"error": f"{type(e).__name__}: {e}", "traceback": tb},
            status_code=500,
        )
    finally:
        # do_build 已硬链接/复制所需文件，上传临时目录可安全删除
        with _cache_lock:
            _active_tmpdirs.discard(upload_tmp)
        shutil.rmtree(upload_tmp, True)


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
# 缓存管理：查看 / 手动清理 PolyFlix 临时目录
# --------------------------------------------------------------------------- #
@app.get("/api/cache/info")
async def cache_info():
    """返回缓存目录路径、总大小、条目数。"""
    path = POLYFLIX_TEMP_DIR or ""
    size, count = 0, 0
    if path and os.path.isdir(path):
        size = _dir_size(path)
        for _root, _dirs, files in os.walk(path):
            count += len(files)
    return {"path": path, "size": size, "count": count}


@app.post("/api/cache/clean")
async def cache_clean():
    """清理 PolyFlix 缓存目录，跳过当前正在使用的目录（构建中 / 待下载）。
    返回释放的字节数、删除条目数、跳过条目数。
    """
    path = POLYFLIX_TEMP_DIR or ""
    if not path or not os.path.isdir(path):
        return {"freed": 0, "removed": 0, "skipped": 0, "path": path}

    # 收集当前正在使用的目录（_builds 里的 + _active_tmpdirs 里的），这些要跳过
    with _cache_lock:
        in_use = {os.path.abspath(info["tmpdir"]) for info in _builds.values() if info.get("tmpdir")}
        in_use.update(os.path.abspath(t) for t in _active_tmpdirs)

    freed = 0
    removed = 0
    skipped = 0
    for name in os.listdir(path):
        full = os.path.abspath(os.path.join(path, name))
        if full in in_use:
            skipped += 1
            continue
        try:
            if os.path.isdir(full):
                freed += _dir_size(full)
                shutil.rmtree(full, True)
            else:
                freed += os.path.getsize(full)
                os.remove(full)
            removed += 1
        except Exception:
            pass

    log(f"手动清理缓存: 删除 {removed} 项，跳过 {skipped} 项（使用中），释放 {fmt_bytes(freed)}")
    return {"freed": freed, "removed": removed, "skipped": skipped, "path": path}


# --------------------------------------------------------------------------- #
# 直接运行：python app.py
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=18181)
