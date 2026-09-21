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
import subprocess
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

import pflx                      # PFLX 双视频格式（free box 藏匿法，与影现播放器共用）
import brand                     # 统一的署名 / 制作信息（zip 注释、MP4 备注）

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


def _set_zip_comment(z) -> None:
    """把制作信息写进 zip 注释（同时用于外层 ZIP 和内层 ZIP）。

    zipfile.ZipFile 与 pyzipper.AESZipFile 都支持 comment 属性（写在 EOCD 尾部，
    不加密、不参与校验）。写入失败只告警，不中断构建。
    """
    try:
        z.comment = brand.zip_comment().encode("utf-8")
    except Exception as e:
        log(f"  ZIP 制作信息写入失败（不致命）: {e}", level="warning")


def fmt_bytes(n: int) -> str:
    """把字节数格式化成人类可读。"""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} TB"


# ZIP End of Central Directory 记录的签名（PK\x05\x06）
_ZIP_EOCD_SIG = b'PK\x05\x06'


def _zip_is_standalone(filepath: str, file_size: int) -> bool | None:
    """文件尾部的 ZIP 结构是不是"从文件头开始"的独立 ZIP。

    True  → 独立 ZIP（普通 .zip 文件）
    False → ZIP 前面还粘着别的数据 → PolyFlix 产物（MP4 + ZIP 拼接）
    None  → 没有 EOCD / 结构异常，判断不了
    """
    if file_size < 22:
        return None
    scan_size = min(file_size, 65557 + 1024)
    with open(filepath, "rb") as f:
        f.seek(-scan_size, 2)
        tail = f.read()
    idx = tail.rfind(_ZIP_EOCD_SIG)
    if idx < 0 or idx + 22 > len(tail):
        return None
    cd_size = int.from_bytes(tail[idx + 12: idx + 16], "little")
    cd_offset = int.from_bytes(tail[idx + 16: idx + 20], "little")
    # EOCD 绝对偏移 = ZIP 起点 + cd_offset + cd_size，反推出 ZIP 起点（普通 zip 为 0）
    zip_start = (file_size - scan_size) + idx - cd_size - cd_offset
    return zip_start == 0


def is_polyflix_product(filepath: str) -> bool:
    """检测一个文件是否是 PolyFlix 产物（两种模式的产物都识别）。

    模式一（ZIP 拼接）：尾部有 EOCD，且它描述的 ZIP 起点不在文件开头
    （前面粘着 MP4）—— 这正是“拼接”的特征，普通 .zip 不会误判。
    模式二（双视频/PFLX）：MP4 + free box 藏匿，用 pflx.is_pflx_product 识别。
    """
    try:
        file_size = os.path.getsize(filepath)
        standalone = _zip_is_standalone(filepath, file_size)
        if standalone is True:
            return False        # 独立 ZIP（普通压缩包），不是产物
        if standalone is False:
            return True         # ZIP 前面粘着 MP4 → 拼接产物
        # 没有 ZIP 结构，再查 PFLX free box（沿 box 链扫描，只读 box 头，成本也很低）
        return pflx.is_pflx_product(filepath)
    except Exception:
        return False

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
                _set_zip_comment(z)
        else:
            with zipfile.ZipFile(out_path, "w", allowZip64=True, **kw) as z:
                for i, (arcname, fpath) in enumerate(entries):
                    log(f"  内层 ZIP [{i+1}/{len(entries)}]: {arcname} ({fmt_bytes(os.path.getsize(fpath))})")
                    _zip_write_stream(z, arcname, fpath)
                _set_zip_comment(z)
        log(f"  内层 ZIP 完成（已写入制作信息注释）: {os.path.getsize(out_path)} 字节")
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
    # 注释里写制作信息（产物被当作 zip 打开时，7-Zip → 文件 → 注释 可见）
    if password:
        with AESZipFile(out_path, "w", encryption=WZ_AES, allowZip64=True, **kw) as z:
            z.setpassword(password.encode())
            for i, (arcname, fpath) in enumerate(entries):
                log(f"  外层 ZIP [{i+1}/{total}]: {arcname} ({fmt_bytes(os.path.getsize(fpath))})")
                z.write(fpath, arcname)
            _set_zip_comment(z)
    else:
        with zipfile.ZipFile(out_path, "w", allowZip64=True, **kw) as z:
            for i, (arcname, fpath) in enumerate(entries):
                log(f"  外层 ZIP [{i+1}/{total}]: {arcname} ({fmt_bytes(os.path.getsize(fpath))})")
                _zip_write_stream(z, arcname, fpath)
            _set_zip_comment(z)
    log(f"  外层 ZIP 完成（已写入制作信息注释）: {os.path.getsize(out_path)} 字节")


def save_upload_to_file(upload: UploadFile, dest: str):
    """流式把上传文件写到磁盘，避免一次性读进内存。"""
    upload.file.seek(0)
    try:
        with open(dest, "wb") as f:
            shutil.copyfileobj(upload.file, f, length=CHUNK_SIZE)
    finally:
        upload.file.close()


def _register_build(mp4_path: str, tail_path: str, download_name: str,
                    total_size: int, tmpdir: str, mode: str = "zip") -> str:
    """登记一次构建结果，返回 download_id。

    tail_path：拼接在 MP4 后面的部分（ZIP 模式 = outer.zip；双视频模式 = free box 文件）。
    产物 = mp4_path 字节流 + tail_path 字节流。mode：zip | dual。
    """
    download_id = uuid.uuid4().hex[:12]
    if len(_builds) >= _MAX_BUILDS:
        oldest_id = next(iter(_builds))
        old = _builds.pop(oldest_id)
        shutil.rmtree(old["tmpdir"], True)
    _builds[download_id] = {
        "mp4_path": mp4_path,
        "tail_path": tail_path,
        "filename": download_name,
        "size": total_size,
        "tmpdir": tmpdir,
        "mode": mode,
    }
    return download_id


def _copy_file_stream(src: str, dest: str, label: str, use_hardlink: bool = True):
    """把 src 弄到 dest：优先硬链接，失败则流式复制。返回 dest。"""
    if use_hardlink:
        try:
            os.link(src, dest)
            log(f"{label} 硬链接完成: {os.path.getsize(dest)} 字节")
            return dest
        except OSError:
            pass
    log(f"{label} 复制中… ({fmt_bytes(os.path.getsize(src))})")
    with open(src, "rb") as f, open(dest, "wb") as out:
        shutil.copyfileobj(f, out, length=CHUNK_SIZE)
    log(f"{label} 复制完成: {os.path.getsize(dest)} 字节")
    return dest


def _find_ffmpeg() -> str | None:
    """定位 ffmpeg（只作兜底）：随包的 tools/ffmpeg/ffmpeg.exe，或系统 PATH。"""
    for rel in (os.path.join("tools", "ffmpeg", "ffmpeg.exe"),
                os.path.join("tools", "ffmpeg", "ffmpeg")):
        p = os.path.join(BASE_DIR, rel)
        if os.path.isfile(p):
            return p
    return shutil.which("ffmpeg")


def _write_comment_ffmpeg(src_path: str, dst_path: str, comment: str) -> bool:
    """兜底方案：ffmpeg 重封装写 ©cmt（`-c copy`，不重新编码）。

    只有 mutagen 认不出这个文件时才会走到这里；找不到 ffmpeg 直接返回 False。
    """
    exe = _find_ffmpeg()
    if not exe:
        return False

    cmd = [
        exe, "-y", "-hide_banner", "-loglevel", "error",
        "-i", src_path,
        "-map", "0",            # 保留所有轨道（视频/音频/字幕/封面），不丢流
        "-c", "copy",           # 不重新编码
        "-map_metadata", "0",   # 沿用原有元数据，只覆盖 comment
        "-metadata", f"comment={comment}",
        "-f", "mp4", dst_path,
    ]
    kwargs = {"stdin": subprocess.DEVNULL, "capture_output": True,
              "encoding": "utf-8", "errors": "replace"}
    if sys.platform == "win32":
        # exe 是无控制台窗口的，子进程必须显式隐藏，否则会闪黑窗
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    try:
        log("写入外壳视频备注（ffmpeg 兜底重封装，不重新编码）…")
        proc = subprocess.run(cmd, **kwargs)
    except Exception as e:
        log(f"调用 ffmpeg 失败，跳过写入视频备注: {e}", level="warning")
        return False

    if proc.returncode != 0 or not os.path.isfile(dst_path) or os.path.getsize(dst_path) == 0:
        err = (proc.stderr or "").strip().splitlines()
        tail = err[-1] if err else "无输出"
        log(f"ffmpeg 写入备注失败（跳过，不影响构建）: {tail}", level="warning")
        try:
            if os.path.exists(dst_path):
                os.remove(dst_path)
        except OSError:
            pass
        return False

    log(f"  外壳视频备注已写入: {os.path.getsize(dst_path)} 字节")
    return True


def write_mp4_comment(src_path: str, dst_path: str, comment: str) -> bool:
    """给外壳 MP4 写入「备注」(©cmt) —— 资源管理器「详细信息 → 备注」可见。

    正常路径：mutagen（纯 Python，200KB，就地改 moov 里的元数据，1GB 文件约 0.07s）。
    它会**先把 src 复制成 dst 再改**，绝不改动用户选的原文件
    （mutagen 是就地修改，所以这里必须真复制，不能用硬链接）。
    mutagen 认不出这个文件时退回 ffmpeg 重封装。
    都失败就跳过 —— 只是少了那条制作信息，隐藏内容与播放都不受影响。
    """
    try:
        from mutagen.mp4 import MP4
    except ImportError:
        log("未安装 mutagen，改用 ffmpeg 写入视频备注", level="warning")
        return _write_comment_ffmpeg(src_path, dst_path, comment)

    try:
        _copy_file_stream(src_path, dst_path, "外壳 MP4", use_hardlink=False)
        m = MP4(dst_path)
        m["\xa9cmt"] = [comment]
        m.save()
        log(f"  外壳视频备注已写入: {os.path.getsize(dst_path)} 字节")
        return True
    except Exception as e:
        log(f"mutagen 写入备注失败，改用 ffmpeg 兜底: {e}", level="warning")
        try:
            if os.path.exists(dst_path):
                os.remove(dst_path)
        except OSError:
            pass
        return _write_comment_ffmpeg(src_path, dst_path, comment)


def _prepare_cover_mp4(mp4_path: str, tmpdir: str) -> tuple[str, int]:
    """把外壳 MP4 落进构建临时目录，并写入制作信息「备注」。返回 (路径, 大小)。

    外壳 mp4 必须放进构建自己的临时目录：/api/build 结束时会删除上传临时目录，
    若直接引用上传路径，下载时文件已不存在。
    写备注失败时返回原样副本，构建照常继续。
    """
    base = os.path.join(tmpdir, "cover.mp4")
    _copy_file_stream(mp4_path, base, "MP4")
    if os.path.getsize(base) == 0:
        return base, 0

    commented = os.path.join(tmpdir, "cover_comment.mp4")
    if write_mp4_comment(base, commented, brand.mp4_comment()):
        try:
            os.remove(base)     # 没备注的副本已无用，省一份磁盘
        except OSError:
            pass
        return commented, os.path.getsize(commented)
    return base, os.path.getsize(base)


def _build_dual(mp4_path: str, hidden_paths: list, mp4_display_name: str, tmpdir: str) -> dict:
    """双视频模式（PFLX）：外壳 MP4（写入制作信息备注）+ free box（载荷 = b 视频原始字节）。

    b 可以是任意格式（mkv/flv/webm/avi…），不转码、不压缩、不加密。
    外壳视频 a 只在有 ffmpeg 时做一次「重封装」（写 ©cmt 备注，不重新编码），
    找不到 ffmpeg 则原样使用。
    普通播放器播 a（free box 被忽略），影现播放器播 b。
    必须恰好一个隐藏文件。
    """
    if len(hidden_paths) != 1:
        raise ValueError(
            f"双视频模式只能隐藏 1 个视频文件（当前 {len(hidden_paths)} 个）。"
            f"需要隐藏多个文件请使用 ZIP 模式。"
        )
    hidden_path = hidden_paths[0]
    hidden_size = os.path.getsize(hidden_path)
    if hidden_size == 0:
        raise ValueError("隐藏视频文件为空")
    mp4_size = os.path.getsize(mp4_path)

    log(f"模式: 双视频")
    log(f"伪装视频: {fmt_bytes(mp4_size)}")
    log(f"隐藏视频: {os.path.basename(hidden_path)} ({fmt_bytes(hidden_size)})")

    # 磁盘空间检查（free box 需落盘，约等于载荷大小；
    # 外壳 MP4 还要多落一份"写入备注元数据"的重封装副本，故按 2 份算；预留余量）
    disk = shutil.disk_usage(tmpdir)
    need = mp4_size * 2 + hidden_size + 64 * 1024 * 1024
    if disk.free < need:
        log(f"⚠️ 磁盘空间不足: 剩余 {fmt_bytes(disk.free)}, 约需 {fmt_bytes(need)}", level="warning")
    else:
        log(f"磁盘空间: 剩余 {fmt_bytes(disk.free)}（约需 {fmt_bytes(need)}）")

    # 构建 free box（载荷 = b 的原始字节，流式写入，边写边算 CRC32）
    freebox_path = os.path.join(tmpdir, "payload.freebox")

    # 落进临时目录 + 写入「备注」制作信息（资源管理器「详细信息 → 备注」可见）。
    # 只改元数据不重编码，free box 之后才拼，隐藏内容与播放都不受影响。
    mp4_path, mp4_size = _prepare_cover_mp4(mp4_path, tmpdir)

    log(f"封装隐藏视频…")
    _last_pct = [-1]

    def _on_progress(done: int, total: int):
        if total <= 256 * 1024 * 1024:
            return  # 小文件不打进度
        pct = done * 100 // total
        if pct != _last_pct[0] and pct % 10 == 0:
            _last_pct[0] = pct
            log(f"    写入隐藏视频: {pct}% ({fmt_bytes(done)} / {fmt_bytes(total)})")

    stats = pflx.write_free_box(hidden_path, freebox_path,
                               name=os.path.basename(hidden_path),
                               progress=_on_progress)
    log(f"隐藏视频封装完成: {stats['box_size']} 字节")

    total_size = mp4_size + stats["box_size"]
    log(f"拼接: MP4({mp4_size}) + freebox({stats['box_size']}) = {total_size} 字节")

    # 派生下载文件名（与 ZIP 模式一致）
    mp4_name = os.path.basename(mp4_display_name)
    base = mp4_name[:-4] if mp4_name.lower().endswith(".mp4") else mp4_name
    download_name = f"{base}-polyflix.mp4"
    log(f"下载文件名: {download_name}")

    download_id = _register_build(mp4_path, freebox_path, download_name, total_size, tmpdir, mode="dual")
    log(f"下载 ID: {download_id}")
    log(f"========== 构建成功 ==========")
    # tmpdir 现由 _builds 持有，从活动集合移除（与 ZIP 模式成功路径一致）
    with _cache_lock:
        _active_tmpdirs.discard(tmpdir)
    return {"download_id": download_id, "filename": download_name, "size": total_size, "mode": "dual"}


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

        # 0) 模式分派：dual = 双视频（PFLX free box），zip = 原有 ZIP 拼接
        if cfg.get("mode", "zip") == "dual":
            return _build_dual(mp4_path, hidden_paths, mp4_display_name, tmpdir)

        # 1) 把 MP4 放进临时目录（硬链接优先）+ 写入外壳「备注」制作信息
        mp4_path, mp4_size = _prepare_cover_mp4(mp4_path, tmpdir)

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
        need += mp4_size  # 写外壳备注时会多出一份 MP4 副本
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
        download_id = _register_build(mp4_path, outer_path, download_name, total_size, tmpdir, mode="zip")

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
            "mode": result.get("mode", "zip"),
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
        for part in (info["mp4_path"], info["tail_path"]):
            with open(part, "rb") as f:
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
