"""PFLX 双视频格式 —— 影藏（构建）与影现播放器（播放）共用的格式定义模块

产物结构（一个完全合法的 MP4）：

    [ a.mp4 原样字节（ftyp/moov/mdat...） ]
    [ free box: size(4) + 'free'(4) [+ largesize(8)]
        └─ PFLX 头部（22 + name_len 字节） + 载荷（b 视频的原始字节）]

PFLX 头部（全部大端）：

    offset  size  字段
    0       4     magic     固定 b"PFLX"
    4       1     version   格式版本，固定为 1
    5       1     flags     标志位（见下）
    6       2     reserved  保留，写 0
    8       8     length    载荷长度（字节数）
    16      4     crc32     载荷的 CRC32（zlib.crc32）
    20      2     name_len  隐藏文件原始名的字节数（UTF-8，上限 65535）
    22      name_len  name  隐藏文件原始名（UTF-8 字节）

flags 位定义（为未来升级预留，当前全部为 0）：

    bit 0 (0x01)  ENCRYPTED  载荷已用 AES-256-CTR 加密（密钥派生自用户密码，
                             IV 存于载荷头部 —— 详见 CLAUDE.md 路线图）
    bit 1..7      保留

兼容性：free box（Free Space Box）是 ISO 14496-12 规范中明确定义的
"内容无关、解析器必须忽略"的盒子，所有标准播放器都会跳过它，
因此普通播放器双击产物只会播放外壳视频 a。
"""

from __future__ import annotations

import os
import struct
import zlib

# ---- 格式常量（两个项目共用，修改须同步 PolyFlixPlayer/pflx.py） ----
MAGIC = b"PFLX"
FORMAT_VERSION = 1

# flags 位（当前未使用，为未来加密等特性预留）
FLAG_ENCRYPTED = 0x01

# 固定头部前 20 字节：magic(4) + version(1) + flags(1) + reserved(2) + length(8) + crc32(4)
_FIXED_HEADER_SIZE = 20
_FIXED_HEADER_FMT = ">4sBBHQ"  # magic, version, flags, reserved, length（crc32 单独 pack）

# name 字段：name_len(2 字节, 大端) + name_bytes(name_len 字节, UTF-8)
_NAME_LEN_FIELD = 2
_MAX_NAME_LEN = 0xFFFF  # 65535，name_len 字段上限（文件名远不会这么长）

# 头部最小字节数（无名字时）：20 + 2 = 22
HEADER_SIZE = _FIXED_HEADER_SIZE + _NAME_LEN_FIELD

# 单个 box 的 size 字段是 32 位；超过 4GB 时需要 64 位 largesize
_LARGE_SIZE_THRESHOLD = 0xFFFFFFFF

# free box 类型标记
_BOX_TYPE_FREE = b"free"


# --------------------------------------------------------------------------- #
# 构建（影藏侧使用）
# --------------------------------------------------------------------------- #
def _encode_name(name: str | None) -> bytes:
    """把隐藏文件名编码为 UTF-8 字节。None / 空串 → 空字节。"""
    if not name:
        return b""
    b = name.encode("utf-8")
    if len(b) > _MAX_NAME_LEN:
        # 超长名截断（极端边界，文件名几乎不可能这么长）
        b = b[:_MAX_NAME_LEN]
    return b


def header_size(name: str | None = None) -> int:
    """给定文件名，返回 PFLX 头部总字节数（固定 20 + 2 + name_len）。"""
    return HEADER_SIZE + len(_encode_name(name))


def make_header(payload_len: int, payload_crc: int, flags: int = 0,
                name: str | None = None) -> bytes:
    """打包 PFLX 头部（20 字节固定头 + 2 字节 name_len + name_bytes）。"""
    fixed = struct.pack(_FIXED_HEADER_FMT, MAGIC, FORMAT_VERSION, flags, 0, payload_len) + \
        struct.pack(">I", payload_crc & 0xFFFFFFFF)
    nb = _encode_name(name)
    return fixed + struct.pack(">H", len(nb)) + nb


def free_box_total_size(payload_len: int, name: str | None = None) -> int:
    """给定载荷长度，返回完整 free box 的总字节数（含 box 头 + PFLX 头）。"""
    # box 头 8 字节；超 4GB 时再补 8 字节 largesize（box 头 16 字节）
    box_payload = header_size(name) + payload_len
    box_header = 8 if 8 + box_payload <= _LARGE_SIZE_THRESHOLD else 16
    return box_header + box_payload


def write_free_box(src_path: str, out_path: str, flags: int = 0,
                   name: str | None = None, progress=None) -> dict:
    """把 src_path 的全部字节封装成 free box 写入 out_path（流式，内存恒定）。

    out 文件布局：box 头（8/16 字节）+ PFLX 头（22 + name_len 字节）+ 载荷。
    name：隐藏文件的原始名（存入头部，播放器读取后用于显示/导出默认名）。
          None 或空串时写 name_len=0（头部仍为 22 字节，不含名信息）。
    progress(done, total) 可选回调，用于进度上报。
    返回 {"box_size", "payload_len", "crc32", "encrypted", "name"}
    """
    payload_len = os.path.getsize(src_path)
    box_size = free_box_total_size(payload_len, name)
    crc = 0

    with open(src_path, "rb") as src, open(out_path, "wb") as out:
        # box 头：size + 'free'（超 4GB 时 size=1 + largesize）
        if box_size <= _LARGE_SIZE_THRESHOLD:
            out.write(struct.pack(">I4s", box_size, _BOX_TYPE_FREE))
        else:
            out.write(struct.pack(">I4sQ", 1, _BOX_TYPE_FREE, box_size))
        # PFLX 头（crc 先占位，两遍不行——载荷可能极大，所以 CRC 边写边算，
        # 但头部必须在载荷前面，因此先把 crc 字段置 0，写完载荷后 seek 回去补写）
        header_pos = out.tell()
        out.write(make_header(payload_len, 0, flags, name))
        # 流式拷贝载荷并计算 CRC
        done = 0
        while True:
            chunk = src.read(8 * 1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
            crc = zlib.crc32(chunk, crc)
            done += len(chunk)
            if progress:
                progress(done, payload_len)
        # 回补真实 CRC
        out.seek(header_pos)
        out.write(make_header(payload_len, crc, flags, name))

    return {
        "box_size": box_size,
        "payload_len": payload_len,
        "crc32": crc & 0xFFFFFFFF,
        "encrypted": bool(flags & FLAG_ENCRYPTED),
        "name": name,
    }


# --------------------------------------------------------------------------- #
# 解析（影现播放器侧使用；影藏侧用它做产物检测）
# --------------------------------------------------------------------------- #
def scan(path: str) -> dict | None:
    """扫描 MP4 顶层 box 链，定位 PFLX 载荷。

    返回：
        {
          "box_offset":   free box 在文件中的起始偏移
          "payload_offset": 载荷（b 视频字节）的起始偏移
          "payload_len":  载荷长度
          "version":      PFLX 格式版本
          "flags":        标志位
          "encrypted":    是否加密
          "crc32":        头部里记录的载荷 CRC32
          "name":         隐藏文件原始名（无名字时为 None）
          "file_size":    文件总大小
        }
    不是 PFLX 产物（或损坏）返回 None。
    """
    try:
        file_size = os.path.getsize(path)
        with open(path, "rb") as f:
            offset = 0
            while offset < file_size:
                head = f.read(8)
                if len(head) < 8:
                    return None
                size32, box_type = struct.unpack(">I4s", head)
                if size32 == 1:
                    # 64 位 largesize
                    large = f.read(8)
                    if len(large) < 8:
                        return None
                    box_size = struct.unpack(">Q", large)[0]
                    box_header = 16
                elif size32 == 0:
                    # size=0：本 box 延伸到文件末尾
                    box_size = file_size - offset
                    box_header = 8
                else:
                    box_size = size32
                    box_header = 8
                if box_size < box_header or offset + box_size > file_size:
                    # box 链损坏（超出了文件范围）→ 非法文件，当作非产物处理
                    return None

                if box_type == _BOX_TYPE_FREE and box_size - box_header >= HEADER_SIZE:
                    payload_header = f.read(_FIXED_HEADER_SIZE)
                    if len(payload_header) == _FIXED_HEADER_SIZE:
                        magic, ver, flags, _reserved, plen = struct.unpack(
                            _FIXED_HEADER_FMT, payload_header[:16])
                        crc = struct.unpack(">I", payload_header[16:20])[0]
                        if magic == MAGIC:
                            # 读 name_len + name 字段
                            if box_size - box_header - _FIXED_HEADER_SIZE < _NAME_LEN_FIELD:
                                return None  # 空间不够 → 损坏
                            nl_bytes = f.read(_NAME_LEN_FIELD)
                            if len(nl_bytes) < _NAME_LEN_FIELD:
                                return None
                            name_len = struct.unpack(">H", nl_bytes)[0]
                            # name_len 不能超出 box 剩余空间（载荷之前）
                            max_avail = box_size - box_header - HEADER_SIZE
                            if name_len > max_avail:
                                return None  # 名字长度超过可用空间 → 损坏
                            name = None
                            if name_len > 0:
                                nb = f.read(name_len)
                                if len(nb) < name_len:
                                    return None
                                try:
                                    name = nb.decode("utf-8")
                                except UnicodeDecodeError:
                                    name = None  # 名字损坏不致命，降级为 None
                            extra = HEADER_SIZE + name_len
                            return {
                                "box_offset": offset,
                                "payload_offset": offset + box_header + extra,
                                "payload_len": plen,
                                "version": ver,
                                "flags": flags,
                                "encrypted": bool(flags & FLAG_ENCRYPTED),
                                "crc32": crc,
                                "name": name,
                                "file_size": file_size,
                            }
                    # 普通 free box（无 PFLX 魔数）→ 跳过，继续扫
                    f.seek(offset + box_size)
                else:
                    f.seek(offset + box_size)
                offset += box_size
    except OSError:
        return None
    return None


def is_pflx_product(path: str) -> bool:
    """快速判断文件是否为 PFLX 双视频产物。"""
    info = scan(path)
    if info is None:
        return False
    # 基本合法性：载荷不能超出文件范围
    return info["payload_offset"] + info["payload_len"] <= info["file_size"]


def verify_payload_crc(path: str, info: dict | None = None) -> bool:
    """流式校验载荷 CRC32（播放器打开产物时可选用，大文件耗时与全盘读取相当）。"""
    if info is None:
        info = scan(path)
    if info is None:
        return False
    crc = 0
    remaining = info["payload_len"]
    with open(path, "rb") as f:
        f.seek(info["payload_offset"])
        while remaining > 0:
            chunk = f.read(min(8 * 1024 * 1024, remaining))
            if not chunk:
                return False
            crc = zlib.crc32(chunk, crc)
            remaining -= len(chunk)
    return (crc & 0xFFFFFFFF) == info["crc32"]


# --------------------------------------------------------------------------- #
# 导出（影现播放器的"导出隐藏视频"功能；测试也用它验证往返一致性）
# --------------------------------------------------------------------------- #
def extract_payload(path: str, dest_path: str, info: dict | None = None,
                    progress=None) -> dict:
    """把 PFLX 载荷原样抽出到 dest_path（流式）。返回统计 dict。"""
    if info is None:
        info = scan(path)
    if info is None:
        raise ValueError("不是 PFLX 产物")
    if info["payload_offset"] + info["payload_len"] > info["file_size"]:
        raise ValueError("载荷长度与文件大小不符，文件可能已损坏")
    remaining = info["payload_len"]
    crc = 0
    with open(path, "rb") as src, open(dest_path, "wb") as out:
        src.seek(info["payload_offset"])
        done = 0
        while remaining > 0:
            chunk = src.read(min(8 * 1024 * 1024, remaining))
            if not chunk:
                raise ValueError("读取提前结束，文件可能已损坏")
            out.write(chunk)
            crc = zlib.crc32(chunk, crc)
            remaining -= len(chunk)
            done += len(chunk)
            if progress:
                progress(done, info["payload_len"])
    if (crc & 0xFFFFFFFF) != info["crc32"]:
        raise ValueError(f"CRC32 校验失败（读得 {crc & 0xFFFFFFFF:08x}，"
                         f"应为 {info['crc32']:08x}），文件可能已损坏")
    return {"payload_len": info["payload_len"], "crc32": crc & 0xFFFFFFFF}
