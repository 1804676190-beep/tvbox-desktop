# TVBox Desktop

Windows 桌面版 TVBox 播放器，对标手机 TVBox App。

## ⬇️ 下载

**最新版本（安装版）：**

👉 [点击下载 TVBox Desktop 安装程序](../../releases/latest/download/TVBox-Desktop-v1.2.0-Setup.exe)

> 下载后双击安装程序，按向导完成安装即可。
> 安装过程会自动配置 mpv 播放器。

**历史版本：** [Releases 页面](../../releases)

---

## 🚀 功能

- 🎬 **海报墙首页** — 自动刮削元数据 (TMDB/豆瓣)，展示海报、评分、简介
- 📡 **订阅源管理** — 支持 TVBox JSON / XML 格式，首次启动自动加载预设源
- 🏪 **仓库管理** — 添加仓库 URL，一键导入多个源
- 🔗 **智能粘贴链接** — 粘贴 URL 自动识别类型：TVBox 源 / 网页视频
- 🌐 **网页视频提取** — 自动从网页中检测 m3u8/mp4/flv 视频资源并转为可用线路
- 📺 **多线路切换** — 详情页支持多线路选择
- ☁️ **网盘挂载** — Alist / WebDAV / **夸克网盘** (扫码授权)
- 📺 **直播频道** — M3U / TXT 格式，分组管理
- 🔍 **全局搜索** — 跨分类搜索影视
- ⭐ **收藏 / 历史** — 持久化存储
- 🎬 **mpv 播放** — 支持各种视频格式
- 🔄 **在线更新检查** — 自动检测新版本

## 🛠️ 从源码运行

```bash
# 安装依赖
pip install -r requirements.txt

# 运行
python main.py
```

## 📦 打包安装程序

```bash
# Windows
build.bat

# 或手动
pip install pyinstaller
pyinstaller tvbox.spec --clean --noconfirm
# 使用 Inno Setup 编译安装程序
iscc installer.iss
```

## 🏗️ 技术栈

| 组件 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| UI | PyQt6 |
| 播放器 | mpv (python-mpv) |
| HTTP | requests |
| XML | BeautifulSoup4 + lxml |
| 元数据 | TMDB API / 豆瓣 |
| 打包 | PyInstaller + Inno Setup |

## ⌨️ 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+S` | 管理订阅源 |
| `Ctrl+R` | 管理仓库 |
| `Ctrl+Shift+V` | 智能粘贴链接 |
| `Ctrl+Shift+Q` | 添加夸克网盘 |
| `Ctrl+O` | 打开网络地址 |
| `Ctrl+L` | 打开本地文件 |
| `Ctrl+Q` | 退出 |
| `Enter` | 搜索 |
