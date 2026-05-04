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

## 后续计划

- [ ] 弹幕支持
- [ ] 视频下载管理器
- [ ] 封面图本地缓存
- [ ] 网盘密码加密存储
- [ ] 多语言支持
- [ ] 投屏功能（DLNA）
