# 影藏 PolyFlix

把文件藏进一段能正常播放的 MP4 视频里。

生成的文件既是合法的 **MP4**（双击就能播），又是合法的 **ZIP**（改后缀为 `.zip` 就能解压）——这叫"多态文件 (polyglot)"。

配合**影现播放器** [PolyFlixPlayer](https://github.com/hcllmsx/PolyFlixPlayer) 这个姊妹项目一起使用体验会更好哟。

## 嵌套结构

```
MP4 外壳（伪装层，正常播放）
 └─ ZIP 外层（改后缀 .zip 解压，可选 AES-256 密码）
     └─ [可选] 内层 ZIP 或 7z（可选密码）
         └─ 要隐藏的文件
```

## 快速开始（Windows）

1. 安装 [Python 3.8+](https://www.python.org/downloads/)（安装时勾选 Add to PATH）
2. 双击 `dev_run.bat`
3. 浏览器自动打开 `http://127.0.0.1:18181`

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

## 解包方法

1. 把 `polyglot.mp4` 改后缀为 `.zip`
2. 解压（设了外层密码则输入）
3. 若有内层压缩包，用 7-Zip 打开（设了内层密码则输入）
4. 得到隐藏文件

> ⚠️ 请勿用于非法用途。

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
| [FFmpeg](https://ffmpeg.org/) / libmpv | 视频解码内核 | https://ffmpeg.org/ |
| [PyInstaller](https://pyinstaller.org/) | 打包成单文件可执行程序 | https://pyinstaller.org/ |

