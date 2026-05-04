# 开发日志

> 技术细节文档，供新同事快速上手开发。

---

## 一、项目概览

**TVBox Desktop** — Windows 桌面版 TVBox 播放器，对标手机 TVBox App。

- **语言**: Python 3.10+
- **UI 框架**: PyQt6
- **播放器**: mpv (python-mpv)
- **打包**: PyInstaller

## 二、环境搭建

### 2.1 快速开始（推荐）

```bash
# Windows 一键安装
install.bat

# Linux/macOS
chmod +x install.sh && ./install.sh
```

### 2.2 手动搭建

```bash
# 1. 安装 Python 3.10+
# 2. 安装依赖
pip install -r requirements.txt

# 3. 安装 mpv
# Windows: winget install mpv.mpv 或 choco install mpv
# macOS:   brew install mpv
# Ubuntu:  sudo apt install mpv libmpv-dev

# 4. 运行
python main.py
```

### 2.3 打包 EXE

```bash
# Windows
build.bat

# 输出在 dist/TVBox Desktop/
# 需要手动复制 mpv-2.dll 到输出目录
```

## 三、目录结构

```
tvbox-desktop/
├── main.py                  # 入口文件 (40行)
├── requirements.txt         # 依赖: PyQt6, python-mpv, requests, bs4, lxml
├── tvbox.spec               # PyInstaller 打包配置
├── install.bat / install.sh # 一键安装
├── build.bat / build.sh     # 一键打包
├── paste_link_converter.py  # 粘贴链接导入模块 (922行)
├── core/                    # 核心逻辑层
│   ├── models.py            # 数据模型 (188行)
│   ├── source_manager.py    # 订阅源解析器 (279行)
│   ├── repository.py        # 仓库管理器 (122行)
│   ├── cloud_drive.py       # 网盘客户端 (265行)
│   └── media_player.py      # mpv 播放器封装 (170行)
├── ui/
│   └── main_window.py       # 主窗口 UI (1946行)
└── .github/workflows/
    └── build.yml            # GitHub Actions 自动构建
```

## 四、核心模块说明

### 4.1 数据模型 (`core/models.py`)

所有数据类使用 `@dataclass`，支持 `to_dict()` / `from_dict()` 序列化。

```python
VideoItem       # 视频条目（含多线路 play_sources）
SourceInfo      # 订阅源（name, url, source_type, enabled）
Repository      # 仓库（name, url, source_count）
CloudDriveConfig # 网盘配置（alist/webdav）
LiveChannel     # 直播频道（name, urls, group）
Category        # 分类（name, type_id, items）
AppState        # 应用状态，持久化到 tvbox_state.json
```

**关键字段**:
- `VideoItem.play_sources`: 所有播放线路 `[{name, episodes: [{name, url}]}]`
- `VideoItem.episodes`: 当前线路的剧集列表
- `AppState`: 管理所有状态，调用 `save()` 写入 JSON

### 4.2 订阅源解析器 (`core/source_manager.py`)

**类**: `SourceManager`

| 方法 | 说明 |
|------|------|
| `fetch_source(source)` | 拉取订阅源，返回 `{categories, live_channels}` |
| `fetch_detail(api_url, vod_id)` | 获取视频详情（含多线路） |
| `search(api_url, keyword)` | 搜索影视 |

**多线路解析逻辑**:
```
vod_play_from = "线路1$$$线路2$$$线路3"
vod_play_url  = "ep1$url1#ep2$url2$$$ep1$url3#ep2$url4$$$..."
```
按 `$$$` 分割后，每条线路独立解析剧集，存入 `VideoItem.play_sources`。

**支持的源格式**:
- TVBox JSON（`sites` + `lives` 字段）
- XML/IPTV 格式
- M3U 直播源（`#EXTINF` + `group-title`）
- TXT 直播源（`频道名,URL` + `分组,#genre#`）

### 4.3 仓库管理器 (`core/repository.py`)

**函数**: `fetch_repository(repo_url) -> list[SourceInfo]`

支持三种仓库格式：
1. JSON 对象: `{"storeHouse": [{sourceName, sourceUrl}]}`
2. JSON 数组: `[{name, url}]`
3. TXT: `名称,URL`

### 4.4 网盘客户端 (`core/cloud_drive.py`)

**AlistClient**:
- `login(username, password)` → 获取 token
- `list_dir(path)` → 目录列表
- `get_download_url(path)` → 播放直链
- `search(keyword, path)` → 搜索文件

**WebDAVClient**:
- `list_dir(path)` → PROPFIND 列目录
- `get_download_url(path)` → 完整 URL

**CloudFile** 属性:
- `is_video`: 是否视频文件（.mp4/.mkv/.avi 等 16 种格式）
- `is_media`: 是否媒体文件（含音频）
- `size_str`: 可读文件大小

### 4.5 播放器封装 (`core/media_player.py`)

**类**: `MediaPlayer`

基于 python-mpv，使用 mpv 嵌入模式（传入窗口句柄 `wid`）。

| 方法 | 说明 |
|------|------|
| `init_player(wid)` | 初始化，嵌入 Qt 窗口 |
| `play(url, title)` | 播放 |
| `stop()` / `pause()` | 停止/暂停 |
| `seek(seconds)` | 跳转 |
| `set_volume(vol)` | 音量 0-100 |
| `toggle_fullscreen()` | 全屏切换 |
| `shutdown()` | 关闭播放器 |

**Windows 特殊配置**: `vo=gpu`, `gpu-context=d3d11`

### 4.6 粘贴链接导入 (`paste_link_converter.py`)

**核心功能**: 粘贴 URL → 自动识别格式 → 解析 → 勾选导入

**PasteLinkDialog**: PyQt6 对话框
- 启动时自动检测剪贴板
- 粘贴即识别类型
- 后台线程解析
- 勾选式导入
- 去重写入 AppState

**支持的链接格式**:
- GitHub Raw JSON/TXT
- TVBox 仓库 JSON（storeHouse/数组/单源）
- TXT 源列表
- M3U 直播源

## 五、UI 架构 (`ui/main_window.py`)

### 5.1 布局

```
┌─────────────────────────────────────────────────┐
│  📺 源: [下拉框]  🔍 [搜索框] [搜索]  🔗粘贴链接 │
├────────────────────────┬────────────────────────┤
│  [🏠首页][🔍搜索]      │                        │
│  [📺直播][☁️网盘]      │    播放器区域 (mpv)     │
│  [⭐收藏][📜历史]      │                        │
│                        │    [控制栏]             │
│  内容区 (卡片/列表)     │    [进度条] [音量]      │
├────────────────────────┴────────────────────────┤
│  状态栏                                         │
└─────────────────────────────────────────────────┘
```

### 5.2 核心组件

| 组件 | 类名 | 说明 |
|------|------|------|
| 视频卡片 | `VideoCard` | 160×240，封面+标题+标签，点击信号 |
| 详情页 | `DetailPage` | 封面+信息+线路选择+剧集网格 |
| 直播页 | `LivePage` | 左侧分组 + 右侧频道列表 |
| 搜索页 | `SearchPage` | 搜索结果卡片网格 |
| 网盘页 | `CloudDrivePage` | 网盘选择+路径导航+文件列表 |
| 源管理 | `SourceDialog` | 源列表+添加+预设 |
| 仓库管理 | `RepoDialog` | 仓库列表+拉取+粘贴链接 |
| 网盘管理 | `CloudDriveDialog` | 网盘配置表单 |
| 粘贴链接 | `PasteLinkDialog` | URL 解析+勾选导入 |

### 5.3 异步机制

```python
class WorkerThread(QThread):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    # 封装任意函数在子线程执行
```

所有网络请求通过 `WorkerThread` 执行，不阻塞 UI。

### 5.4 暗色主题

全套深色 Fusion 风格，主色调:
- 背景: `#0f0f1a`
- 面板: `#16162a`
- 卡片: `#1a1a2e`
- 强调: `#3a3a6e` / `#5a5aaa`
- 文字: `#eee` / `#aaa` / `#888`

样式通过 `MainWindow.STYLE` 字符串统一设置。

## 六、数据持久化

状态保存在 `tvbox_state.json`:

```json
{
  "sources": [{"name": "...", "url": "...", "source_type": "json", "enabled": true}],
  "repositories": [{"name": "...", "url": "...", "enabled": true, "source_count": 0}],
  "cloud_drives": [{"name": "...", "drive_type": "alist", "url": "...", "token": "..."}],
  "favorites": [{"name": "...", "url": "...", "pic": "..."}],
  "history": [{"name": "...", "url": "...", "pic": "..."}],
  "last_source_index": 0
}
```

## 七、快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+S` | 管理订阅源 |
| `Ctrl+R` | 管理仓库 |
| `Ctrl+Shift+V` | 粘贴链接导入 |
| `Ctrl+O` | 打开网络地址 |
| `Ctrl+L` | 打开本地文件 |
| `Ctrl+Q` | 退出 |
| `Enter` | 搜索 |

## 八、CI/CD

GitHub Actions 自动构建：
- **触发条件**: push 到 main、打 tag `v*`、手动触发
- **构建环境**: windows-latest + Python 3.12
- **产物**: `TVBox-Desktop-win64.zip`（含 EXE + mpv-2.dll）
- **Release**: 打 tag 自动发布到 GitHub Releases

## 九、扩展开发指南

### 添加新的订阅源格式

在 `core/source_manager.py` 的 `SourceManager` 中添加新的解析方法，并在 `fetch_source()` 中调用。

### 添加新的网盘类型

在 `core/cloud_drive.py` 中实现新的客户端类（参考 `AlistClient`），然后在 `ui/main_window.py` 的 `CloudDrivePage` 中添加支持。

### 添加新的页面

1. 创建新的 QWidget 子类
2. 在 `MainWindow._setup_ui()` 中添加到 `self.left_tabs`
3. 连接信号（如 `play_requested`）

### 修改主题

编辑 `MainWindow.STYLE` 字符串，使用 Qt 样式表语法。

## 十、注意事项

1. **PyQt6 兼容性**: 不要使用 PyQt5 的 API（如 `AA_EnableHighDpiScaling`）
2. **线程安全**: UI 更新必须在主线程，用信号槽通信
3. **SSL 警告**: `verify=False` 会产生警告，已在 main.py 中抑制
4. **mpv 依赖**: 运行时需要系统安装 mpv 或有 mpv-2.dll
5. **编码**: 所有文件使用 UTF-8
