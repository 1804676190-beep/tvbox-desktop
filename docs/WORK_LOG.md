# 工作日志

> 记录项目从零到交付的完整过程，供新同事了解项目背景。

---

## 2026-05-04 — 项目启动与完成

### 09:42 — 需求接收
- 收到用户提供的两份文档：`REBUILD_PROMPT.md`（需求概要）和 `PROJECT_SPEC.md`（技术规格）
- 确认项目目标：构建 TVBox Desktop，一个 Windows 桌面版 TVBox 播放器

### 09:46 — 功能追加：粘贴链接导入
- 用户提出新需求：增加"粘贴网站链接自动转为仓库线路"的入口
- 设计方案：识别 URL 类型（仓库/源/直播）→ 后台解析 → 勾选导入
- 实现模块：`paste_link_converter.py`（922行），含对话框 + 静默转换两种模式

### 09:48 — 全项目构建
- 用户要求完整重建项目
- 按规格文档逐文件实现，共 20 个文件，3934 行 Python 代码
- 所有文件语法检查通过

### 09:52 — 一键安装脚本
- 用户要求提供一键安装脚本
- 实现 `install.bat`（Windows）和 `install.sh`（Linux/macOS）
- 功能：自动检测/安装 Python、pip 依赖、mpv 播放器、创建快捷方式
- 内置国内镜像兜底（清华 pypi）

### 09:55 — CI/CD 配置
- 用户要求提供 EXE 下载链接
- 方案 B：GitHub Actions 自动构建
- 创建 `.github/workflows/build.yml`：push 自动打包，打 tag 自动发布 Release

### 09:58 — 代码推送
- 用户提供 GitHub 仓库地址
- 推送过程中遇到 token 权限问题（缺少 `workflow` scope）
- 解决：用户新建带 workflow 权限的 token，通过 GitHub API 补推 workflow 文件

### 10:16 — Bug 修复：PyQt6 兼容性
- 用户反馈运行报错：`AttributeError: 'ApplicationAttribute' has no attribute 'AA_EnableHighDpiScaling'`
- 原因：该属性是 PyQt5 的，PyQt6 默认启用高 DPI，已移除此 API
- 修复：删除 `QCoreApplication.setAttribute(...)` 调用
- 通过 GitHub API 更新文件，重新触发构建

### 10:24 — 重新构建
- 用户下载的是旧版打包文件，需要重新构建
- 删除旧 tag，重建 tag 触发新的 GitHub Actions 构建

### 11:00 — 用户反馈四项问题
用户测试后提出四个问题：
1. 界面太过简单，UI 很生硬
2. 内置仓库为 0 个源
3. 粘贴链接后自动关闭，未生效
4. 应该增加在线更新功能

### 11:05 — 问题定位与分析

**问题 3 根因（粘贴链接失效）：**
- `paste_link_converter.py` 第 610/620 行：
  ```python
  from models import Repository as RepoModel    # ❌ 错误
  from core.models import SourceInfo             # ❌ 错误
  ```
- 实际模块路径是 `core.models`，不是 `models`
- `_write_to_state()` 抛出 `ModuleNotFoundError`，被 Qt 吞掉
- 对话框 800ms 后自动 `accept()` 关闭，用户只看到"闪退"

**问题 2 根因（0 个源）：**
- `PRESET_REPOSITORIES` 只定义在 `repository.py` 中
- `MainWindow.__init__()` 只检查 `if self.state.sources:` 才加载
- 首次启动 state 为空 → 跳过加载 → 用户看到空界面
- 需要手动去「管理仓库 → 预设仓库」添加，不直观

### 11:08 — 修复实施

**Fix 1: UI 增强**
- 全局 `STYLE` 改用 `qlineargradient` 渐变（按钮、Tab、工具栏、控制栏）
- `VideoCard` 圆角 8→10px，hover 边框高亮 + 渐变背景
- `QSlider` 手柄改用 `qradialgradient` 径向渐变
- 输入框 focus 时背景微变，字体增加 `Microsoft YaHei`
- 控制栏、播放器区域、详情页返回按钮全部升级渐变
- 首页新增欢迎横幅（渐变圆角卡片）

**Fix 2: 首次启动自动加载预设**
- 新增 `_auto_add_presets()` 方法
- 检测到 repositories 和 sources 均为空时自动执行
- 添加 3 个预设仓库 + 3 个预设源
- 状态栏提示 `🎉 已自动添加预设仓库和源`

**Fix 3: 粘贴链接导入修复**
- `paste_link_converter.py`：
  - `from models import Repository` → `from core.models import Repository`
  - `from models import SourceInfo` → `from core.models import SourceInfo`

**Fix 4: 在线更新检查**
- 新建 `core/updater.py`（99 行）
  - 调用 GitHub Releases API 获取最新版本
  - `_compare_versions()` 版本号比较
  - `UpdateInfo` 数据类，含下载链接、文件大小
- `main_window.py` 帮助菜单新增「🔄 检查更新」
- 弹窗显示：版本号、发布时间、更新大小、更新日志
- 点击「前往下载」打开浏览器到 Release 页面

### 11:10 — 提交与构建
- 提交 `351bdc0`：3 个文件，+298 行，-61 行
- GitHub Actions 构建 #10 自动触发，1 分 26 秒完成

### 11:12 — 发布 v1.1.0
- 创建 tag `v1.1.0`（通过 GitHub API）
- Actions 自动构建并发布 Release
- 产物：`TVBox-Desktop-win64.zip`（45MB，含 EXE + mpv-2.dll）
- 下载地址：`https://github.com/1804676190-beep/tvbox-desktop/releases/download/v1.1.0/TVBox-Desktop-win64.zip`

---

## 关键决策记录

| 决策 | 原因 |
|------|------|
| PyQt6 而非 Tkinter | 专业级 UI，支持嵌入 mpv 窗口 |
| mpv 而非 VLC | 格式支持最全，Python 绑定成熟 |
| 暗色 Fusion 主题 | 跨平台一致，自定义方便 |
| dataclass 数据模型 | 简洁，自带序列化支持 |
| QThread 异步 | 所有网络请求在子线程，不阻塞 UI |
| GitHub Actions 构建 | 免费、自动、支持 Release 附件 |

## 已知问题

1. **mpv-2.dll 需手动复制** — mpv 不能完全打包进 EXE
2. **封面图无缓存** — 每次启动重新加载
3. **网盘密码明文存储** — 存在 tvbox_state.json 中
4. **GitHub Actions mpv 下载** — SourceForge 链接可能不稳定

## 版本历史

| 版本 | 日期 | 主要变更 |
|------|------|----------|
| v1.0.0 | 2026-05-04 | 初版发布，完整功能 |
| v1.1.0 | 2026-05-04 | UI 增强、预设源自动加载、粘贴链接修复、在线更新 |

## 后续计划

- [ ] 封面图本地缓存
- [ ] 网盘密码加密存储
- [ ] 弹幕支持
- [ ] 视频下载管理器
- [ ] 多语言支持
- [ ] 投屏功能（DLNA）
