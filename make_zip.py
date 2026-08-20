"""把 dist/PolyFlix 目录打包成 zip，用于分发。

用法：
    python make_zip.py

输出：
    dist/PolyFlix-v<版本号>-portable.zip          ← 压缩包（含校验值注释）
    dist/PolyFlix-v<版本号>-portable.zip.sha256   ← SHA-256 校验文件

zip 内部结构：
    PolyFlix/                  ← 外层文件夹（解压后得到一个干净的 PolyFlix 目录）
      ├─ PolyFlix.exe
      └─ _internal/...

用 Python 标准库 zipfile/hashlib 实现，不依赖 PowerShell 的 Compress-Archive
（从 PowerShell 7 环境调用 Windows PowerShell 的 Compress-Archive 时，
 PSModulePath 继承会导致模块自动加载失败）。

校验值说明：
  - zip 注释里的哈希 = 压缩内容的哈希（加注释前计算）
  - .sha256 文件里的哈希 = 完整 zip 的哈希（加注释后计算，用于分发校验）
  收件人下载 zip 后，用 .sha256 文件校验即可。
"""
import hashlib
import os
import sys
import zipfile
from datetime import datetime

SRC_DIR = os.path.join("dist", "PolyFlix")
# zip 内外层文件夹名（解压后得到的目录名）
TOP_DIR_IN_ZIP = "PolyFlix"

# 额外打包进 zip 的素材文件（不参与运行，仅作为附带的样片/素材分发）。
# 元素为 (源文件绝对/相对路径, 在 zip 内相对于 TOP_DIR_IN_ZIP 的子路径)。
# 源文件不存在时只打印告警，不会中断打包（避免没有样片时无法出包）。
BONUS_FILES = [
    (os.path.join("_temp", "PolyFlix样片.mp4"), "PolyFlix样片.mp4"),
]


def read_version():
    """读取 VERSION 文件（打包脚本从项目根目录运行，路径相对即可）。"""
    try:
        with open("VERSION", "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "?"


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def file_sha256(path):
    """流式计算文件的 SHA-256，返回十六进制字符串。"""
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)  # 1MB 分块
            if not chunk:
                break
            sha256.update(chunk)
    return sha256.hexdigest()


def main():
    if not os.path.isdir(SRC_DIR):
        print(f"[错误] 找不到目录：{SRC_DIR}")
        print("       请先运行 build_exe.py 完成打包。")
        sys.exit(1)

    version = read_version()

    # 输出文件名带版本号：PolyFlix-v26.8.8-portable.zip
    zip_filename = f"PolyFlix-v{version}-portable.zip"
    out_zip = os.path.join("dist", zip_filename)
    sha256_file = out_zip + ".sha256"

    # 清理旧的输出文件（含旧命名 PolyFlix-portable.zip 及可能残留的 .md5）
    stale_patterns = [
        out_zip,
        sha256_file,
        out_zip + ".md5",
        os.path.join("dist", "PolyFlix-portable.zip"),         # 旧命名（无版本号）
        os.path.join("dist", "PolyFlix-portable.zip.sha256"),  # 旧命名
        os.path.join("dist", "PolyFlix-portable.zip.md5"),     # 旧命名
    ]
    for old in stale_patterns:
        if os.path.exists(old):
            os.remove(old)

    # ---- 收集所有文件 ----
    files = []
    total_size = 0
    for root, dirs, filenames in os.walk(SRC_DIR):
        for name in filenames:
            full = os.path.join(root, name)
            arc = os.path.relpath(full, SRC_DIR)
            files.append((full, arc))
            total_size += os.path.getsize(full)

    # ---- 收集额外素材文件（样片等，放到 zip 内 PolyFlix/ 下与 exe 同目录）----
    bonus = []  # (full_path, arcname_in_zip)
    for src_rel, sub in BONUS_FILES:
        if os.path.isfile(src_rel):
            arcname = TOP_DIR_IN_ZIP + "/" + sub.replace(os.sep, "/")
            bonus.append((src_rel, arcname))
            total_size += os.path.getsize(src_rel)
        else:
            print(f"[告警] 额外素材不存在，已跳过：{src_rel}")

    total_files = len(files) + len(bonus)
    print(f"正在压缩 {total_files} 个文件（约 {human_size(total_size)}）…")
    if bonus:
        print(f"  其中 {len(bonus)} 个为附带的素材样片：")
        for src_rel, arcname in bonus:
            print(f"    + {arcname}  ← {src_rel}")
    print(f"输出文件：{zip_filename}")

    # ---- 第 1 步：创建 zip（内层加 PolyFlix/ 前缀）----
    count = 0
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for full, arc in files:
            # zip 内用正斜杠（跨平台兼容），外层套一个 PolyFlix/ 文件夹
            arcname = TOP_DIR_IN_ZIP + "/" + arc.replace(os.sep, "/")
            zf.write(full, arcname)
            count += 1
            if count % 200 == 0:
                print(f"  已处理 {count}/{total_files} 个文件…")
        # 追加额外素材（与 exe 同目录）
        for src_rel, arcname in bonus:
            zf.write(src_rel, arcname)
            count += 1
            print(f"  已附带素材：{arcname}")

    out_size = os.path.getsize(out_zip)
    print(f"\n[1/3] 压缩完成：{human_size(out_size)}（原始 {human_size(total_size)}）")

    # ---- 第 2 步：计算 zip 内容的 SHA-256（加注释前）----
    sha256_content = file_sha256(out_zip)
    print(f"[2/3] 计算校验值…")
    print(f"      内容 SHA-256: {sha256_content}")

    # ---- 将校验值作为注释写入 zip ----
    build_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    comment_text = (
        f"PolyFlix Portable v{version}\n"
        f"Build: {build_time}\n"
        f"Files: {len(files) + len(bonus)}\n"
        f"Size: {human_size(out_size)}\n"
        f"\n"
        f"==== 校验值（压缩内容，不含本注释）====\n"
        f"SHA-256: {sha256_content}\n"
        f"\n"
        f"完整文件校验值（含本注释）见随附的 .sha256 文件。\n"
        f"校验命令：Get-FileHash {zip_filename} -Algorithm SHA256"
    )
    with zipfile.ZipFile(out_zip, "a") as zf:
        zf.comment = comment_text.encode("utf-8")

    # ---- 第 3 步：计算完整 zip 的 SHA-256（加注释后，用于分发校验）----
    sha256_final = file_sha256(out_zip)

    # ---- 写校验文件（标准格式：<hash>  <filename>）----
    with open(sha256_file, "w", encoding="utf-8") as f:
        f.write(f"{sha256_final}  {zip_filename}\n")

    print(f"\n[3/3] 校验文件已生成：")
    print(f"      {sha256_file}")
    print(f"        SHA-256: {sha256_final}")

    print(f"\n============================================")
    print(f"  全部完成！可分发的文件：")
    print(f"    {out_zip}          ({human_size(out_size)})")
    print(f"    {sha256_file}")
    print(f"============================================")
    print(f"\nzip 内结构：{TOP_DIR_IN_ZIP}/ → PolyFlix.exe + _internal/"
          + (" + 附带素材样片" if bonus else ""))
    print(f"zip 注释已写入校验值（用 7-Zip 打开 → 文件 → 注释 可查看）。")
    print(f"收件人校验方法：")
    print(f"  Get-FileHash {zip_filename} -Algorithm SHA256")
    print(f"将结果与 .sha256 文件比对即可。")


if __name__ == "__main__":
    main()
