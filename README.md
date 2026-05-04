# TVBox Desktop

Windows 桌面版 TVBox 播放器，对标手机 TVBox App。

## ⬇️ 下载

**最新构建（自动更新）：**

👉 [点击下载 TVBox-Desktop-win64.zip](../../releases/latest/download/TVBox-Desktop-win64.zip)

> 下载后解压，运行 `TVBox Desktop.exe` 即可。
> 如果无法播放视频，请将 `mpv-2.dll` 放到解压目录。

**历史版本：** [Releases 页面](../../releases)

---

## 🚀 功能

- 📡 **订阅源管理** — 支持 TVBox JSON / XML 格式
- 🏪 **仓库管理** — 添加仓库 URL，一键导入多个源
- 🔗 **粘贴链接导入** — 粘贴 URL 自动识别并导入仓库/源
- 📺 **多线路切换** — 详情页支持多线路选择
- ☁️ **网盘挂载** — Alist / WebDAV，浏览目录直接播放
- 📺 **直播频道** — M3U / TXT 格式，分组管理
- 🔍 **全局搜索** — 跨分类搜索影视
- ⭐ **收藏 / 历史** — 持久化存储
- 🎬 **mpv 播放** — 支持各种视频格式

## 🛠️ 从源码运行

```bash
# 安装依赖
pip install -r requirements.txt

# 运行
python main.py

# 或使用一键安装脚本
# Windows: install.bat
# Linux/macOS: chmod +x install.sh && ./install.sh
```

## 📦 打包 EXE

```bash
# Windows
build.bat

# 或手动
pip install pyinstaller
pyinstaller tvbox.spec --clean --noconfirm
# 复制 mpv-2.dll 到 dist/TVBox Desktop/
```

## 🏗️ 技术栈

| 组件 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| UI | PyQt6 |
| 播放器 | mpv (python-mpv) |
| HTTP | requests |
| XML | BeautifulSoup4 + lxml |
| 打包 | PyInstaller |

## 📁 项目结构

```
tvbox-desktop/
├── main.py                  # 入口
├── requirements.txt         # 依赖
├── install.bat / install.sh # 一键安装
├── build.bat / build.sh     # 一键打包
├── core/
│   ├── models.py            # 数据模型
│   ├── source_manager.py    # 订阅源解析
│   ├── repository.py        # 仓库管理
│   ├── cloud_drive.py       # 网盘客户端
│   └── media_player.py      # mpv 播放器
├── ui/
│   └── main_window.py       # 主窗口 UI
└── paste_link_converter.py  # 粘贴链接导入
```

## ⌨️ 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+S` | 管理订阅源 |
| `Ctrl+R` | 管理仓库 |
| `Ctrl+Shift+V` | 粘贴链接导入 |
| `Ctrl+O` | 打开网络地址 |
| `Ctrl+L` | 打开本地文件 |
| `Ctrl+Q` | 退出 |
| `Enter` | 搜索 |
