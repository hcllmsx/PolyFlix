# 影藏 PolyFlix

把文件藏进一段能正常播放的 MP4 视频里。

生成的文件既是合法的 **MP4**（双击就能播），又是合法的 **ZIP**（改后缀为 `.zip` 就能解压）——这叫"多态文件 (polyglot)"。

配合影现播放器姊妹项目使用体验更佳：
- [PolyFlixPlayer](https://github.com/hcllmsx/PolyFlixPlayer)（基于 Flutter + media_kit，支持 Windows / Android）——可直接播放影藏多态视频里的隐藏内容，无需解包、无需改后缀，现已深度集成本地离线 AI 语音转录字幕、大模型智能翻译与双语字幕对照功能。

## 嵌套结构

```
MP4 外壳（伪装层，正常播放）
 └─ ZIP 外层（改后缀 .zip 解压，可选 AES-256 密码）
     └─ [可选] 内层 ZIP 或 7z（可选密码）
         └─ 要隐藏的文件
```

## 快速开始（Windows）

1. 安装 [Python 3.8+](https://www.python.org/downloads/)（安装时勾选 Add to PATH）
2. 双击 `1-run_menu.bat`，选择 `[1] 本地运行`
3. 浏览器自动打开 `http://127.0.0.1:18181`

> 打包成便携版 exe：同样双击 `1-run_menu.bat`，选择 `[2] 打包为 exe`，产物在 `dist\PolyFlix\`，并附带 zip 分发包。不需要额外准备 ffmpeg。

## 手动启动

```bash
pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 18181
```

浏览器打开 `http://127.0.0.1:18181`。

## 使用方法

1. **选伪装视频**：拖一个 MP4 进来（当外壳）
2. **选要隐藏的文件**：拖一个或多个文件进来
3. **配置嵌套**：
   - 外层 ZIP 可选加密码（AES-256）
   - 内层可选再加一层 ZIP 或 7z（可选密码）
   - 左侧"结构预览"会实时显示嵌套层次
4. **构建** → 下载 `polyglot.mp4`

## 产物里的制作信息

每个产物都带署名（官网 / 作者 / 版本 / 制作时间），既不破坏隐藏内容也不影响播放：

| 模式 | 制作信息落在哪 | 怎么看 |
|------|----------------|--------|
| MP4 + ZIP | 外层 ZIP 与内层 ZIP 的 **zip 注释** | 7-Zip 打开产物 → 文件 → 注释 |
| MP4 + ZIP（内层 7z） | 只有外层 ZIP 有注释 | 同上（7z 格式本身没有注释位） |
| 双视频（MP4 + MP4） | 外壳 MP4 的 **「备注」** 元数据 | 资源管理器 → 右键属性 → 详细信息 → 备注 |

隐藏的那个文件本身不会被改动。写入外壳 MP4 用的是 [mutagen](https://github.com/quodlibet/mutagen)（纯 Python，200KB）：**就地修改 moov 里的元数据条目**，音视频数据一字节不动，不重新编码、不改轨道数量，1GB 文件约 0.07 秒。

> 因此**不需要 ffmpeg**。只有 mutagen 认不出某个畸形文件时才会退回系统里的 ffmpeg，两者都没有则跳过写备注（产物照常生成，只是少一条制作信息）。

## 解包方法

1. 把 `polyglot.mp4` 改后缀为 `.zip`
2. 解压（设了外层密码则输入）
3. 若有内层压缩包，用 7-Zip 打开（设了内层密码则输入）
4. 得到隐藏文件

> ⚠️ 请勿用于非法用途。

## 产物能再打包吗

| 用在哪个位置 | 是否允许 | 原因 |
|--------------|----------|------|
| 外壳伪装视频 | ❌ 拦下并提示 | 再拼一层会让原有隐藏数据夹在文件中间，标准工具取不出来（数据会丢） |
| 文件隐藏模式的「要隐藏的文件」 | ✅ 允许（套娃） | 解压得到产物本身，再解一次即可 |
| 双视频模式的「隐藏视频」 | ❌ 拦下并提示 | 影现播放器只会播放它的外壳视频，内层解不出来，等于白藏一层；要嵌套请用文件隐藏模式 |

## 反馈与建议

遇到问题或有新想法？欢迎通过问卷告诉我们：[软件意见建议反馈收集表](https://docs.qq.com/form/page/DRHJ3bmd6Q3RqaENT)。

## 开源协议

本项目基于 [GNU General Public License v3.0](LICENSE)（GPL-3.0）开源。

这意味着你可以自由使用、学习、修改和再分发本项目的源代码，但任何基于本项目或其衍生部分的发行版本，也必须以 GPL-3.0 协议继续开源，并附带本协议全文。详细条款见项目根目录的 `LICENSE` 文件。

## 致谢

本项目站在以下成熟开源方案的肩膀上，在此致以谢意：

| 项目 | 用途 | 主页 |
|------|------|------|
| [Python](https://www.python.org/) | 运行时与开发语言 | https://www.python.org/ |
| [FastAPI](https://fastapi.tiangolo.com/) | Web 后端框架（构建逻辑服务） | https://fastapi.tiangolo.com/ |
| [Uvicorn](https://www.uvicorn.org/) | ASGI 服务器 | https://www.uvicorn.org/ |
| [pywebview](https://pywebview.flowrl.com/) | 桌面 Webview 窗口封装 | https://pywebview.flowrl.com/ |
| [py7zr](https://github.com/miurahr/py7zr) | 7z 压缩（内层嵌套） | https://github.com/miurahr/py7zr |
| [pyzipper](https://github.com/danver/pyzipper) | AES-256 加密 ZIP（外层压缩） | https://github.com/danver/pyzipper |
| [mutagen](https://github.com/quodlibet/mutagen) | 给外壳 MP4 写「备注」(©cmt)，纯 Python 就地改元数据 | https://github.com/quodlibet/mutagen |
| [FFmpeg](https://ffmpeg.org/) | 影现播放器的解码内核；影藏这边仅在 mutagen 失效时兜底 | https://ffmpeg.org/ |
| [PyInstaller](https://pyinstaller.org/) | 打包成单文件可执行程序 | https://pyinstaller.org/ |

