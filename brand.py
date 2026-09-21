"""影藏 PolyFlix —— 统一的署名 / 制作信息

产物的"制作信息"在两处落地，文本都由本模块生成，改官网/作者只需改这里：

    1) ZIP 层注释（7-Zip 打开产物 → 文件 → 注释）
       外层 ZIP 始终会写；内层 ZIP 也会写；内层 7z 格式没有注释位，故不写。
    2) 双视频模式外壳 MP4 的「备注」(©cmt)
       Windows 资源管理器「详细信息 → 备注」可见；隐藏的那个视频不动。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

# ---- 软件身份信息（改官网/作者改这里） ----
APP_NAME = "影藏 PolyFlix"
OFFICIAL_SITE = "https://polyflix.sxrec.com/"
AUTHOR_NAME = "火车啦啦"
AUTHOR_URL = "https://space.bilibili.com/255947051"

# 版本号位置：源码运行 = 项目根目录；PyInstaller 打包后 = _MEIPASS 根目录
_BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
_VERSION_FILE = os.path.join(_BASE_DIR, "VERSION")


def app_version() -> str:
    """读取 VERSION 文件（打包时打进 _MEIPASS），读不到返回空串。"""
    try:
        with open(_VERSION_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def now_string() -> str:
    """当前时间的可读字符串，用于写在制作信息里。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def zip_comment() -> str:
    """ZIP 注释：多行明细（7-Zip → 文件 → 注释）。"""
    ver = app_version()
    lines = [
        f"本文件由 {APP_NAME} 打包制作而成",
        f"官网：{OFFICIAL_SITE}",
        f"作者：{AUTHOR_NAME}  {AUTHOR_URL}",
    ]
    if ver:
        lines.append(f"版本：v{ver}")
    lines.append(f"制作时间：{now_string()}")
    return "\r\n".join(lines)


def mp4_comment() -> str:
    """MP4「备注」(©cmt)：单行，保证资源管理器里读着顺。

    多行文本在资源管理器「备注」列里通常只显示一行，所以这里压成一行。
    """
    ver = app_version()
    parts = [
        f"本文件由 {APP_NAME} 打包制作而成",
        f"官网 {OFFICIAL_SITE}",
        f"作者 {AUTHOR_NAME} {AUTHOR_URL}",
    ]
    if ver:
        parts.append(f"v{ver}")
    return " ｜ ".join(parts)
