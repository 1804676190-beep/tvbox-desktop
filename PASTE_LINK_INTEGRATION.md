# 粘贴链接自动导入 — 集成指南

## 新增文件

将 `paste_link_converter.py` 放入项目根目录（与 `main.py` 同级）。

## 集成到 `ui/main_window.py`

### 1. 在文件顶部添加 import

```python
from paste_link_converter import PasteLinkDialog, quick_paste_import
```

### 2. 在工具栏添加「粘贴链接」按钮

找到工具栏创建代码（通常在 `__init__` 或 `_setup_toolbar` 中），添加：

```python
# --- 在现有工具栏按钮之后添加 ---
self.paste_link_btn = QPushButton('🔗 粘贴链接')
self.paste_link_btn.setToolTip('粘贴链接自动识别并导入仓库/源 (Ctrl+V)')
self.paste_link_btn.clicked.connect(self._open_paste_link_dialog)
self.toolbar.addWidget(self.paste_link_btn)
```

### 3. 在菜单栏「文件」菜单中添加入口

找到菜单栏创建代码，添加：

```python
# --- 在文件菜单中添加 ---
file_menu.addSeparator()
paste_action = QAction('🔗 粘贴链接导入...', self)
paste_action.setShortcut('Ctrl+V')  # 注意：需要处理焦点冲突
paste_action.setToolTip('粘贴链接自动识别并导入仓库/源')
paste_action.triggered.connect(self._open_paste_link_dialog)
file_menu.addAction(paste_action)
```

> **注意**：`Ctrl+V` 会与文本框的粘贴冲突。建议改为 `Ctrl+Shift+V`，或者在全局 `keyPressEvent` 中判断焦点。

### 4. 在仓库管理对话框中添加快捷入口

在 `RepoDialog` 类中添加：

```python
def __init__(self, parent=None, state=None):
    # ... 现有代码 ...
    
    # 添加粘贴链接按钮
    self.paste_link_btn = QPushButton('🔗 粘贴链接导入')
    self.paste_link_btn.setToolTip('从剪贴板粘贴仓库链接，自动解析并导入')
    self.paste_link_btn.clicked.connect(self._paste_link_import)
    # 放到按钮行中
    btn_layout.addWidget(self.paste_link_btn)

def _paste_link_import(self):
    """粘贴链接导入"""
    from paste_link_converter import PasteLinkDialog
    dialog = PasteLinkDialog(parent=self, state=self.state)
    dialog.converted.connect(self._on_link_imported)
    dialog.exec()

def _on_link_imported(self, repos, sources):
    """链接导入完成回调"""
    # 刷新仓库列表
    self._refresh_repo_list()
    self._refresh_source_list()
```

### 5. 添加主窗口方法

在 `MainWindow` 类中添加：

```python
def _open_paste_link_dialog(self):
    """打开粘贴链接对话框"""
    dialog = PasteLinkDialog(parent=self, state=self.state)
    dialog.converted.connect(self._on_paste_link_converted)
    dialog.exec()

def _on_paste_link_converted(self, repos, sources):
    """粘贴链接导入完成"""
    total = sum(len(r.sources) for r in repos) + len(sources)
    self.statusBar().showMessage(f'✅ 已导入 {total} 项', 5000)
    # 刷新源列表下拉框
    self._refresh_source_dropdown()
    # 如果当前在首页，刷新分类
    if hasattr(self, '_refresh_current_category'):
        self._refresh_current_category()
```

### 6.（可选）全局快捷键支持

如果想在任意位置用快捷键触发，可以在 `MainWindow` 的 `keyPressEvent` 中添加：

```python
def keyPressEvent(self, event):
    # Ctrl+Shift+V: 粘贴链接导入
    if event.modifiers() == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
        if event.key() == Qt.Key.Key_V:
            # 检查焦点是否在文本框上
            focused = QApplication.focusWidget()
            if not isinstance(focused, (QLineEdit, QTextEdit, QPlainTextEdit)):
                self._open_paste_link_dialog()
                return
    super().keyPressEvent(event)
```

## 快捷粘贴（无需对话框）

如果希望更简洁——在任意位置检测到剪贴板有仓库链接时直接弹确认框：

```python
# 在 MainWindow.__init__ 或合适位置
# 监听剪贴板变化（可选，比较激进）
# 或者通过菜单/按钮触发

def _quick_paste(self):
    """快捷粘贴 — 不弹对话框，直接解析+确认"""
    if quick_paste_import(self.state, parent=self):
        self.statusBar().showMessage('✅ 链接已导入', 3000)
        self._refresh_source_dropdown()
```

## 效果预览

```
┌─────────────────────────────────────────────────────┐
│  🔗 粘贴链接导入                                      │
├─────────────────────────────────────────────────────┤
│                                                     │
│  链接输入                                            │
│  ┌──────────────────────────────────┬──────┬──────┐ │
│  │ https://example.com/tv.json      │📋粘贴│🔍解析│ │
│  └──────────────────────────────────┴──────┴──────┘ │
│  支持: TVBox JSON仓库 / TXT源列表 / M3U直播源        │
│                                                     │
│  识别为: 📦 仓库链接                                  │
│                                                     │
│  解析结果                                            │
│  ┌─────────────────────────────────────────────────┐│
│  │ 📦 仓库: example/tv  (3 个源)                    ││
│  │                                                  ││
│  │  ☑  源1  (json)                                  ││
│  │  ☑  源2  (json)                                  ││
│  │  ☑  源3  (json)                                  ││
│  └─────────────────────────────────────────────────┘│
│  ☑ 全选                           共 3 项            │
│                                                     │
│  📄 查看原始内容                                      │
│                                                     │
│                          ✅ 导入选中项    取消        │
└─────────────────────────────────────────────────────┘
```

## 支持的链接格式

| 格式 | 示例 | 自动识别 |
|------|------|---------|
| GitHub Raw JSON | `raw.githubusercontent.com/.../tv.json` | ✅ |
| GitHub Pages JSON | `xxx.github.io/.../tv.json` | ✅ |
| TVBox 仓库 JSON | 含 `storeHouse` 字段 | ✅ |
| JSON 数组仓库 | `[{name, url}, ...]` | ✅ |
| TVBox 单源 JSON | 含 `sites` + `lives` | ✅ |
| TXT 源列表 | `名称,URL` 格式 | ✅ |
| M3U 直播源 | `#EXTINF` 格式 | ✅ |
| 视频直链 | `.mp4/.mkv/...` | ❌（不导入） |
