# 新同事对接指南

> 5 分钟了解项目，30 分钟跑起来，开始贡献代码。

---

## 👋 你好！

欢迎加入 TVBox Desktop 项目。这是一份快速上手指南。

## 第一步：了解项目（5 分钟）

**TVBox Desktop** 是一个 Windows 桌面视频播放器，对标手机上的 TVBox App。

核心功能：
- 📺 通过订阅源浏览和播放影视
- 🏪 仓库管理（一个 URL 导入多个订阅源）
- 🔗 粘贴链接自动导入
- ☁️ 网盘挂载（Alist / WebDAV）
- 📺 直播频道
- 🎬 mpv 播放器

**技术栈**: Python 3.10+ / PyQt6 / mpv / requests / BeautifulSoup4

## 第二步：搭建环境（10 分钟）

### 方式 A：一键安装（推荐）

```bash
# Windows
install.bat

# Linux/macOS
chmod +x install.sh && ./install.sh
```

会自动安装 Python 依赖和 mpv 播放器。

### 方式 B：手动安装

```bash
# 克隆仓库
git clone https://github.com/1804676190-beep/tvbox-desktop.git
cd tvbox-desktop

# 创建虚拟环境（推荐）
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate  # Linux/macOS

# 安装依赖
pip install -r requirements.txt

# 安装 mpv
# Windows: winget install mpv.mpv
# macOS:   brew install mpv
# Ubuntu:  sudo apt install mpv libmpv-dev

# 运行
python main.py
```

## 第三步：熟悉代码（15 分钟）

### 代码结构一图流

```
用户操作 → ui/main_window.py (UI层)
              ↓ 信号
         core/source_manager.py (业务逻辑)
              ↓
         core/models.py (数据模型)
              ↓
         tvbox_state.json (持久化)
```

### 必读文件（按顺序）

| 顺序 | 文件 | 行数 | 读什么 |
|------|------|------|--------|
| 1 | `core/models.py` | 188 | 数据结构，一切的基础 |
| 2 | `core/source_manager.py` | 279 | 订阅源解析，核心业务 |
| 3 | `core/repository.py` | 122 | 仓库管理，格式简单 |
| 4 | `core/cloud_drive.py` | 265 | 网盘客户端 |
| 5 | `core/media_player.py` | 170 | mpv 封装 |
| 6 | `ui/main_window.py` | 1946 | UI 主文件，最复杂 |
| 7 | `paste_link_converter.py` | 922 | 粘贴链接功能 |

### 关键概念

**多线路**：一个视频可能有多个播放源（线路），用 `$$$` 分隔。
```python
VideoItem.play_sources = [
    {"name": "线路1", "episodes": [{"name": "第1集", "url": "..."}]},
    {"name": "线路2", "episodes": [...]},
]
```

**异步 WorkerThread**：所有网络请求在子线程执行。
```python
self._worker = WorkerThread(某个函数, 参数...)
self._worker.finished.connect(回调函数)
self._worker.start()
```

**AppState**：全局状态管理器，自动持久化到 JSON。
```python
self.state = AppState.load()   # 加载
self.state.save()              # 保存
self.state.add_history(video)  # 添加历史
```

## 第四步：开始开发

### 常见任务

**添加新页面**:
```python
# 1. 创建 QWidget 子类
class MyPage(QWidget):
    play_requested = pyqtSignal(str, str)
    # ...

# 2. 在 MainWindow._setup_ui() 中添加
self.my_page = MyPage()
self.left_tabs.addTab(self.my_page, '🎯 我的页面')

# 3. 连接信号
self.my_page.play_requested.connect(self._play_url)
```

**添加新的源格式**:
```python
# 在 core/source_manager.py 的 SourceManager 中
def _parse_new_format(self, content: str) -> dict:
    # 解析逻辑...
    return {'categories': [...], 'live_channels': [...]}
```

**修改主题颜色**:
```python
# 编辑 ui/main_window.py 中的 MainWindow.STYLE
# 修改 CSS 变量即可全局生效
```

### 运行和调试

```bash
# 直接运行
python main.py

# 查看打印日志（网络请求、解析结果等）
# 所有 print() 都带 [模块名] 前缀，方便 grep
```

### 打包测试

```bash
# Windows
build.bat
# 输出在 dist/TVBox Desktop/
```

## 第五步：协作流程

1. 从 `main` 分支创建特性分支: `git checkout -b feat/xxx`
2. 开发完成后提交: `git commit -m "feat: 添加xxx功能"`
3. 推送并创建 PR
4. GitHub Actions 自动构建验证
5. 合并后自动更新 Release

### Commit 规范

```
feat: 新功能
fix: 修复
docs: 文档
style: 格式
refactor: 重构
test: 测试
ci: CI/CD
```

## 📚 更多文档

- `docs/WORK_LOG.md` — 完整工作日志（时间线、决策记录）
- `docs/DEV_LOG.md` — 技术开发日志（架构、API、扩展指南）
- `README.md` — 项目说明
- `PASTE_LINK_INTEGRATION.md` — 粘贴链接功能集成说明

## ❓ 遇到问题？

1. 先看 `docs/DEV_LOG.md` 的"注意事项"
2. 搜索代码中的 `print()` 输出
3. 检查 `tvbox_state.json` 状态文件
4. 问就对了
