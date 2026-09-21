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
from datetime import datetime

# ============================================================
#  exe 元信息配置（右键 exe → 属性 → 详细信息 里显示的字段）
#  想改公司名/版权持有人，直接改下面两行即可；版本号自动读 VERSION 文件。
# ============================================================
APP_NAME        = "影藏 PolyFlix"                       # 产品名称 / 内部名
COMPANY_NAME    = "hcllmsx"                       # 公司名称
COPYRIGHT_HOLDER = "hcllmsx"                      # 版权持有人
DESCRIPTION    = "影藏 PolyFlix - 视频多态文件工具"     # 文件说明
ORIGINAL_EXE   = "PolyFlix.exe"                         # 原始文件名

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(HERE, "VERSION")
VERSION_INFO_FILE = os.path.join(HERE, "version_info.txt")

# 不需要打包 ffmpeg：外壳 MP4 的「备注」由 mutagen（纯 Python，200KB）写入，
# 就地改 moov 元数据，不重新编码，1GB 文件约 0.07s。
# （万一 mutagen 认不出某个畸形文件，会自动退回系统里的 ffmpeg，缺了也只是少一条备注）


def read_version():
    """读取 VERSION 文件，返回字符串如 '26.8.8'。"""
    with open(VERSION_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()


def parse_version_tuple(ver_str):
    """把 '26.8.8' 解析成 4 元组 (26, 8, 8, 0)，每段 0-65535。"""
    parts = [int(p) for p in ver_str.split(".") if p.strip().isdigit()]
    while len(parts) < 4:
        parts.append(0)
    parts = parts[:4]
    return tuple(parts)


def gen_version_info():
    """生成 PyInstaller 版本信息文件内容（Windows VS_VERSIONINFO 格式）。"""
    ver_str = read_version()
    ver_tuple = parse_version_tuple(ver_str)
    ver_4 = ".".join(str(n) for n in ver_tuple)          # 26.8.8.0
    year = datetime.now().year
    copyright_str = f"© {year} {COPYRIGHT_HOLDER}. 保留所有权利。"

    # PyInstaller 版本信息文件用 UTF-8 编码，中文可正常写入。
    # 字段对照（exe 属性 → 详细信息）：
    #   CompanyName      → 公司名称
    #   FileDescription  → 文件说明
    #   FileVersion      → 文件版本
    #   ProductName      → 产品名称
    #   ProductVersion   → 产品版本
    #   LegalCopyright   → 版权
    return f"""# UTF-8
# 自动生成，请勿手动编辑（由 build_exe.py 根据 VERSION 生成）。
VSVersionInfo(
  ffi=FixedFileInfo(
    # filevers / prodvers 必须是 4 元组 (major, minor, build, revision)
    filevers={ver_tuple},
    prodvers={ver_tuple},
    mask=0x3f,        # 有效位掩码
    flags=0x0,        # VS_FF_* 属性位
    OS=0x40004,       # VOS_NT_WINDOWS32
    fileType=0x1,     # VFT_APP（应用程序）
    subtype=0x0,      # 未定义
    date=(0, 0)       # 创建日期时间戳（不设置）
  ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        u'040904B0',   # LangID_English(US) + CodePage_Unicode
        [
        StringStruct(u'CompanyName', u'{COMPANY_NAME}'),
        StringStruct(u'FileDescription', u'{DESCRIPTION}'),
        StringStruct(u'FileVersion', u'{ver_4}'),
        StringStruct(u'InternalName', u'{APP_NAME}'),
        StringStruct(u'LegalCopyright', u'{copyright_str}'),
        StringStruct(u'OriginalFilename', u'{ORIGINAL_EXE}'),
        StringStruct(u'ProductName', u'{APP_NAME}'),
        StringStruct(u'ProductVersion', u'{ver_str}'),
        ])
      ]),
    VarFileInfo([VarStruct(u'Translation', [0x0409, 1200])])
  ]
)
"""


def write_version_info():
    """把版本信息写入 version_info.txt，供 PyInstaller --version-file 使用。"""
    content = gen_version_info()
    with open(VERSION_INFO_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"已生成版本信息文件：{os.path.basename(VERSION_INFO_FILE)}")


cmd = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--name", "PolyFlix",
    "--onedir",          # 目录模式，启动快（比 --onefile 快很多）
    "--windowed",        # 无控制台黑窗，纯桌面应用
    "--icon", "static/polyflix-favicon.ico",  # exe 图标
    # exe 版本元信息（右键属性 → 详细信息）
    "--version-file", VERSION_INFO_FILE,
    # 静态文件 & 模板 & 版本号打进 exe
    "--add-data", f"static{os.pathsep}static",
    "--add-data", f"templates{os.pathsep}templates",
    "--add-data", f"VERSION{os.pathsep}.",  # VERSION 是文件，放到 _MEIPASS 根目录（不能写 "VERSION;VERSION"，那会变成 _MEIPASS/VERSION/VERSION）
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

def main():
    # 先生成版本信息文件，再打包
    write_version_info()

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


if __name__ == "__main__":
    main()
