"""
粘贴链接自动转仓库/源 — 功能模块
====================================
用法:
    from paste_link_converter import PasteLinkDialog, auto_convert_link

    # 方式1: 弹出对话框（集成到 UI）
    dialog = PasteLinkDialog(parent=self)
    dialog.converted.connect(self._on_link_converted)
    dialog.exec()

    # 方式2: 静默转换（后台调用）
    result = auto_convert_link("https://example.com/tv.json")
    if result:
        repos, sources = result
"""

import re
import json
import requests
from dataclasses import dataclass, field
from typing import Optional, Callable

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QGroupBox, QCheckBox, QListWidget,
    QListWidgetItem, QProgressBar, QMessageBox, QFrame, QApplication
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QPalette


# ============================================================
#  数据结构
# ============================================================

@dataclass
class ConvertedSource:
    """解析出的订阅源"""
    name: str
    url: str
    source_type: str = "json"   # json / xml / m3u
    source_kind: str = "source" # source / live
    repo_name: str = ""

@dataclass
class ConvertedRepo:
    """解析出的仓库"""
    name: str
    url: str
    sources: list = field(default_factory=list)  # list[ConvertedSource]


# ============================================================
#  URL 识别与解析
# ============================================================

# 已知仓库/源 URL 的正则模式
REPO_URL_PATTERNS = [
    # GitHub raw 文件 (JSON/TXT)
    r'https?://raw\.githubusercontent\.com/.+\.(?:json|txt)',
    # GitHub Pages
    r'https?://[a-z0-9-]+\.github\.io/.+\.(?:json|txt)',
    # 通用 TVBox JSON 源
    r'https?://.+/tv/.+\.json',
    r'https?://.+/tvbox/.+\.json',
    # 通用 TXT 列表
    r'https?://.+/tv/.+\.txt',
    r'https?://.+/live/.+\.(?:txt|m3u)',
    # 常见 TVBox 仓库域名
    r'https?://(?:fantaiying|ok321|tvbox|tv\.bailian|ghproxy).+\.(?:json|txt)',
]

# 直播源特征
LIVE_URL_PATTERNS = [
    r'https?://.+\.m3u(?:8)?(?:\?.*)?$',
    r'https?://.+/live/.+\.(?:txt|m3u)',
    r'https?://.+/(?:iptv|live|channel).+\.(?:txt|m3u)',
]

# 视频直链特征（排除误判）
VIDEO_URL_PATTERNS = [
    r'https?://.+\.(?:mp4|mkv|avi|flv|ts|m3u8)(?:\?.*)?$',
]


def guess_link_type(url: str) -> str:
    """
    猜测链接类型
    返回: 'repository' | 'source' | 'live' | 'video' | 'unknown'
    """
    url_lower = url.lower().strip()

    # 直播源
    for pat in LIVE_URL_PATTERNS:
        if re.match(pat, url_lower):
            return 'live'

    # 视频直链（不是源）
    for pat in VIDEO_URL_PATTERNS:
        if re.match(pat, url_lower):
            return 'video'

    # 仓库（包含多个源的列表）
    for pat in REPO_URL_PATTERNS:
        if re.match(pat, url_lower):
            # JSON/TXT 后缀大概率是仓库或源
            if url_lower.endswith('.json'):
                return 'repository'  # 可能是仓库 JSON 或单个源 JSON，需要拉取后判断
            if url_lower.endswith('.txt'):
                return 'repository'  # TXT 格式的源列表

    return 'unknown'


def fetch_and_parse_url(url: str, timeout: int = 15) -> dict:
    """
    拉取 URL 内容并解析
    返回: {
        'type': 'repository' | 'source' | 'live' | 'unknown',
        'data': ConvertedRepo | list[ConvertedSource] | None,
        'raw': str,
        'error': str | None
    }
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        resp = requests.get(url, headers=headers, timeout=timeout, verify=False)
        resp.raise_for_status()
        content = resp.text.strip()
    except Exception as e:
        return {'type': 'error', 'data': None, 'raw': '', 'error': f'请求失败: {e}'}

    # 尝试解析为 JSON
    try:
        data = json.loads(content)
        return _parse_json_content(url, data, content)
    except json.JSONDecodeError:
        pass

    # 尝试解析为 M3U / TXT 直播源
    if '#EXTINF' in content or '#EXTM3U' in content:
        return _parse_m3u_content(url, content)

    # 尝试解析为 TXT 格式的源列表 (名称,URL)
    sources = _parse_txt_source_list(url, content)
    if sources:
        repo = ConvertedRepo(
            name=_extract_repo_name(url),
            url=url,
            sources=sources
        )
        return {'type': 'repository', 'data': repo, 'raw': content, 'error': None}

    return {'type': 'unknown', 'data': None, 'raw': content, 'error': '无法识别的格式'}


def _parse_json_content(url: str, data, raw: str) -> dict:
    """解析 JSON 内容"""

    # 格式1: {"storeHouse": [...]} — 仓库
    if isinstance(data, dict) and 'storeHouse' in data:
        repo = ConvertedRepo(name=_extract_repo_name(url), url=url)
        for item in data['storeHouse']:
            src = ConvertedSource(
                name=item.get('sourceName', item.get('name', '未命名')),
                url=item.get('sourceUrl', item.get('url', '')),
                source_type='json',
                repo_name=repo.name
            )
            if src.url:
                repo.sources.append(src)
        return {'type': 'repository', 'data': repo, 'raw': raw, 'error': None}

    # 格式2: JSON 数组 — 仓库 (每个元素是一个源)
    if isinstance(data, list) and len(data) > 0:
        # 检查是否是源列表（每个元素有 name+url）
        if isinstance(data[0], dict) and ('url' in data[0] or 'sourceUrl' in data[0]):
            repo = ConvertedRepo(name=_extract_repo_name(url), url=url)
            for item in data:
                src = ConvertedSource(
                    name=item.get('name', item.get('sourceName', '未命名')),
                    url=item.get('url', item.get('sourceUrl', '')),
                    source_type='json',
                    repo_name=repo.name
                )
                if src.url:
                    repo.sources.append(src)
            return {'type': 'repository', 'data': repo, 'raw': raw, 'error': None}

    # 格式3: TVBox 单个源 {"sites": [...], "lives": [...]}
    if isinstance(data, dict) and ('sites' in data or 'lives' in data):
        sources = []

        # 解析站点源
        for site in data.get('sites', []):
            if site.get('type') in (0, 1, 4):  # 普通/API/Spider
                src = ConvertedSource(
                    name=site.get('name', site.get('key', '未命名')),
                    url=site.get('api', ''),
                    source_type='json',
                    source_kind='source'
                )
                if src.url:
                    sources.append(src)

        # 解析直播源
        for live in data.get('lives', []):
            src = ConvertedSource(
                name=live.get('name', '直播'),
                url=live.get('url', ''),
                source_type='m3u',
                source_kind='live'
            )
            if src.url:
                sources.append(src)

        if sources:
            return {'type': 'source', 'data': sources, 'raw': raw, 'error': None}

    return {'type': 'unknown', 'data': None, 'raw': raw, 'error': 'JSON 格式不匹配已知模式'}


def _parse_m3u_content(url: str, content: str) -> dict:
    """解析 M3U 直播源"""
    sources = []
    lines = content.split('\n')
    current_name = ''

    for line in lines:
        line = line.strip()
        if line.startswith('#EXTINF:'):
            # 提取频道名
            match = re.search(r',(.+)$', line)
            if match:
                current_name = match.group(1).strip()
            else:
                current_name = '未知频道'
        elif line and not line.startswith('#'):
            if current_name:
                src = ConvertedSource(
                    name=current_name,
                    url=line,
                    source_type='m3u',
                    source_kind='live'
                )
                sources.append(src)
                current_name = ''

    if sources:
        return {'type': 'live', 'data': sources, 'raw': content, 'error': None}
    return {'type': 'unknown', 'data': None, 'raw': content, 'error': 'M3U 内容为空'}


def _parse_txt_source_list(url: str, content: str) -> list:
    """解析 TXT 格式的源列表"""
    sources = []
    for line in content.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        # 格式: 名称,URL 或 名称 URL
        parts = re.split(r'[,，\s]+', line, maxsplit=1)
        if len(parts) == 2:
            name, src_url = parts
            if src_url.startswith('http'):
                src = ConvertedSource(
                    name=name.strip(),
                    url=src_url.strip(),
                    source_type='json',
                    repo_name=_extract_repo_name(url)
                )
                sources.append(src)
    return sources


def _extract_repo_name(url: str) -> str:
    """从 URL 提取仓库名"""
    # 尝试提取有意义的名称
    patterns = [
        (r'github\.com/([^/]+)/([^/]+)', lambda m: f'{m.group(1)}/{m.group(2)}'),
        (r'([^/]+)\.github\.io/([^/]+)', lambda m: f'{m.group(1)}/{m.group(2)}'),
        (r'/tv/([^/?]+)\.json', lambda m: m.group(1)),
        (r'/([^/?]+)\.(?:json|txt)', lambda m: m.group(1)),
    ]
    for pat, extract in patterns:
        m = re.search(pat, url)
        if m:
            return extract(m)
    # fallback: 用域名
    m = re.search(r'https?://([^/]+)', url)
    return m.group(1) if m else '未知仓库'


def auto_convert_link(url: str) -> Optional[tuple]:
    """
    静默转换链接
    返回: (repos: list[ConvertedRepo], sources: list[ConvertedSource]) 或 None
    """
    url = url.strip()
    if not url.startswith('http'):
        return None

    result = fetch_and_parse_url(url)
    if result['error']:
        return None

    repos = []
    sources = []

    if result['type'] == 'repository' and result['data']:
        repos.append(result['data'])
    elif result['type'] in ('source', 'live') and result['data']:
        if isinstance(result['data'], list):
            sources.extend(result['data'])
        else:
            sources.append(result['data'])

    return (repos, sources) if (repos or sources) else None


# ============================================================
#  异步解析线程
# ============================================================

class LinkParseThread(QThread):
    """后台线程解析链接"""
    finished = pyqtSignal(dict)  # fetch_and_parse_url 的结果
    progress = pyqtSignal(str)   # 状态消息

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self):
        self.progress.emit(f'正在解析: {self.url}')
        result = fetch_and_parse_url(self.url)
        self.finished.emit(result)


# ============================================================
#  粘贴链接对话框
# ============================================================

class PasteLinkDialog(QDialog):
    """
    粘贴链接自动转仓库/源 对话框

    用法:
        dialog = PasteLinkDialog(parent=self, state=self.state)
        dialog.converted.connect(self._on_link_converted)
        dialog.exec()
    """

    # 信号: (repos: list[ConvertedRepo], sources: list[ConvertedSource])
    converted = pyqtSignal(list, list)

    STYLE = """
    QDialog {
        background: #0f0f1a;
        color: #eee;
    }
    QGroupBox {
        border: 1px solid #333;
        border-radius: 6px;
        margin-top: 10px;
        padding-top: 15px;
        font-weight: bold;
        color: #aaa;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
    }
    QLineEdit {
        background: #1a1a2e;
        border: 1px solid #333;
        border-radius: 4px;
        padding: 8px 12px;
        color: #eee;
        font-size: 13px;
    }
    QLineEdit:focus {
        border-color: #5a5aaa;
    }
    QLineEdit::placeholder {
        color: #555;
    }
    QPushButton {
        background: #2a2a4e;
        border: 1px solid #3a3a6e;
        border-radius: 4px;
        padding: 8px 16px;
        color: #eee;
        font-size: 13px;
    }
    QPushButton:hover {
        background: #3a3a6e;
        border-color: #5a5aaa;
    }
    QPushButton:pressed {
        background: #4a4a8e;
    }
    QPushButton:disabled {
        background: #1a1a2e;
        color: #555;
        border-color: #222;
    }
    QPushButton#pasteBtn {
        background: #1a3a2e;
        border-color: #2a6a3e;
    }
    QPushButton#pasteBtn:hover {
        background: #2a5a3e;
        border-color: #3a8a4e;
    }
    QPushButton#importBtn {
        background: #1a2a4e;
        border-color: #3a5a8e;
        font-weight: bold;
    }
    QPushButton#importBtn:hover {
        background: #2a3a6e;
        border-color: #4a6a9e;
    }
    QTextEdit {
        background: #1a1a2e;
        border: 1px solid #333;
        border-radius: 4px;
        padding: 8px;
        color: #aaa;
        font-family: Consolas, 'Courier New', monospace;
        font-size: 11px;
    }
    QListWidget {
        background: #1a1a2e;
        border: 1px solid #333;
        border-radius: 4px;
        padding: 4px;
        color: #eee;
        font-size: 12px;
    }
    QListWidget::item {
        padding: 6px 8px;
        border-radius: 3px;
    }
    QListWidget::item:hover {
        background: #2a2a4e;
    }
    QListWidget::item:selected {
        background: #3a3a6e;
    }
    QProgressBar {
        background: #1a1a2e;
        border: 1px solid #333;
        border-radius: 3px;
        text-align: center;
        color: #aaa;
        height: 20px;
    }
    QProgressBar::chunk {
        background: #3a5a8e;
        border-radius: 2px;
    }
    QLabel {
        color: #aaa;
    }
    QLabel#titleLabel {
        color: #eee;
        font-size: 15px;
        font-weight: bold;
    }
    QLabel#statusLabel {
        color: #888;
        font-size: 11px;
    }
    QLabel#resultTitle {
        color: #5a8aaa;
        font-weight: bold;
    }
    QCheckBox {
        color: #aaa;
        spacing: 6px;
    }
    QCheckBox::indicator {
        width: 16px;
        height: 16px;
        border: 1px solid #444;
        border-radius: 3px;
        background: #1a1a2e;
    }
    QCheckBox::indicator:checked {
        background: #3a5a8e;
        border-color: #5a7aae;
    }
    """

    def __init__(self, parent=None, state=None):
        super().__init__(parent)
        self.state = state  # AppState 实例，用于直接导入
        self._parse_thread = None
        self._parse_result = None
        self._selected_items = []  # 勾选的项目

        self.setWindowTitle('🔗 粘贴链接导入')
        self.setMinimumSize(560, 520)
        self.resize(600, 580)
        self.setStyleSheet(self.STYLE)

        self._setup_ui()
        self._connect_signals()

        # 启动时自动检测剪贴板
        QTimer.singleShot(200, self._auto_paste_from_clipboard)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        # 标题
        title = QLabel('🔗 粘贴链接，自动识别并导入')
        title.setObjectName('titleLabel')
        layout.addWidget(title)

        # 输入区
        input_group = QGroupBox('链接输入')
        input_layout = QVBoxLayout(input_group)

        url_row = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText('粘贴仓库/订阅源/直播源链接...')
        url_row.addWidget(self.url_input, 1)

        self.paste_btn = QPushButton('📋 粘贴')
        self.paste_btn.setObjectName('pasteBtn')
        self.paste_btn.setFixedWidth(80)
        url_row.addWidget(self.paste_btn)

        self.parse_btn = QPushButton('🔍 解析')
        self.parse_btn.setObjectName('importBtn')
        self.parse_btn.setFixedWidth(80)
        url_row.addWidget(self.parse_btn)

        input_layout.addLayout(url_row)

        # 快捷提示
        hint = QLabel('支持: TVBox JSON仓库 / TXT源列表 / M3U直播源 / GitHub链接')
        hint.setObjectName('statusLabel')
        input_layout.addWidget(hint)

        layout.addWidget(input_group)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # indeterminate
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # 状态标签
        self.status_label = QLabel('')
        self.status_label.setObjectName('statusLabel')
        layout.addWidget(self.status_label)

        # 结果区
        result_group = QGroupBox('解析结果')
        result_layout = QVBoxLayout(result_group)

        self.result_title = QLabel('')
        self.result_title.setObjectName('resultTitle')
        result_layout.addWidget(self.result_title)

        self.result_list = QListWidget()
        self.result_list.setMinimumHeight(160)
        result_layout.addWidget(self.result_list)

        # 全选/取消
        select_row = QHBoxLayout()
        self.select_all_cb = QCheckBox('全选')
        self.select_all_cb.setChecked(True)
        select_row.addWidget(self.select_all_cb)
        select_row.addStretch()

        self.item_count_label = QLabel('')
        self.item_count_label.setObjectName('statusLabel')
        select_row.addWidget(self.item_count_label)

        result_layout.addLayout(select_row)

        # 原始内容预览（可折叠）
        self.raw_preview = QTextEdit()
        self.raw_preview.setPlaceholderText('原始内容预览...')
        self.raw_preview.setMaximumHeight(100)
        self.raw_preview.hide()
        result_layout.addWidget(self.raw_preview)

        self.toggle_raw_btn = QPushButton('📄 查看原始内容')
        self.toggle_raw_btn.setFixedWidth(140)
        result_layout.addWidget(self.toggle_raw_btn)

        result_group.hide()
        self.result_group = result_group
        layout.addWidget(result_group)

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.import_btn = QPushButton('✅ 导入选中项')
        self.import_btn.setObjectName('importBtn')
        self.import_btn.setFixedWidth(140)
        self.import_btn.setEnabled(False)
        btn_row.addWidget(self.import_btn)

        self.close_btn = QPushButton('取消')
        self.close_btn.setFixedWidth(80)
        btn_row.addWidget(self.close_btn)

        layout.addLayout(btn_row)

    def _connect_signals(self):
        self.paste_btn.clicked.connect(self._paste_from_clipboard)
        self.parse_btn.clicked.connect(self._start_parse)
        self.url_input.returnPressed.connect(self._start_parse)
        self.close_btn.clicked.connect(self.reject)
        self.import_btn.clicked.connect(self._do_import)
        self.select_all_cb.stateChanged.connect(self._toggle_select_all)
        self.toggle_raw_btn.clicked.connect(self._toggle_raw_preview)

        # 粘贴时自动触发解析
        self.url_input.textChanged.connect(self._on_url_changed)

    def _auto_paste_from_clipboard(self):
        """启动时自动从剪贴板粘贴"""
        clipboard = QApplication.clipboard()
        text = clipboard.text().strip()
        if text and text.startswith('http'):
            self.url_input.setText(text)
            # 不自动解析，让用户确认
            self.status_label.setText('📋 已从剪贴板读取链接，点击「解析」开始')

    def _paste_from_clipboard(self):
        """粘贴按钮"""
        clipboard = QApplication.clipboard()
        text = clipboard.text().strip()
        if text:
            self.url_input.setText(text)

    def _on_url_changed(self, text: str):
        """URL 变化时更新提示"""
        text = text.strip()
        if text and text.startswith('http'):
            link_type = guess_link_type(text)
            type_names = {
                'repository': '📦 仓库链接',
                'source': '📡 订阅源',
                'live': '📺 直播源',
                'video': '🎬 视频直链（不支持导入）',
                'unknown': '❓ 未知类型（将尝试解析）',
            }
            self.status_label.setText(f'识别为: {type_names.get(link_type, "未知")}')
        else:
            self.status_label.setText('')

    def _start_parse(self):
        """开始解析"""
        url = self.url_input.text().strip()
        if not url:
            self.status_label.setText('⚠️ 请输入链接')
            return
        if not url.startswith('http'):
            self.status_label.setText('⚠️ 链接格式不正确，需要 http(s):// 开头')
            return

        # 禁用按钮，显示进度
        self.parse_btn.setEnabled(False)
        self.import_btn.setEnabled(False)
        self.progress_bar.show()
        self.status_label.setText(f'🔄 正在解析...')
        self.result_group.hide()

        # 启动后台线程
        self._parse_thread = LinkParseThread(url)
        self._parse_thread.finished.connect(self._on_parse_finished)
        self._parse_thread.start()

    def _on_parse_finished(self, result: dict):
        """解析完成"""
        self.parse_btn.setEnabled(True)
        self.progress_bar.hide()

        self._parse_result = result
        self.result_list.clear()

        if result['error']:
            self.status_label.setText(f'❌ {result["error"]}')
            self.result_group.hide()
            return

        items = []  # (name, url, type_str, checked)

        if result['type'] == 'repository' and result['data']:
            repo = result['data']
            self.result_title.setText(f'📦 仓库: {repo.name}  ({len(repo.sources)} 个源)')
            for src in repo.sources:
                items.append((f'{src.name}  ({src.source_type})', src.url, 'source'))
            self.result_group.show()

        elif result['type'] == 'source' and result['data']:
            sources = result['data'] if isinstance(result['data'], list) else [result['data']]
            self.result_title.setText(f'📡 订阅源: {len(sources)} 个站点')
            for src in sources:
                kind = '📺 直播' if src.source_kind == 'live' else '📡 源'
                items.append((f'{kind} {src.name}', src.url, src.source_kind))
            self.result_group.show()

        elif result['type'] == 'live' and result['data']:
            sources = result['data'] if isinstance(result['data'], list) else [result['data']]
            self.result_title.setText(f'📺 直播源: {len(sources)} 个频道')
            for src in sources:
                items.append((f'📺 {src.name}', src.url, 'live'))
            self.result_group.show()

        else:
            self.status_label.setText('❓ 无法识别该链接的内容')
            self.result_group.hide()
            return

        # 填充列表（带勾选）
        for name, url, item_type in items:
            item = QListWidgetItem(f'  ☑  {name}')
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, {'url': url, 'type': item_type, 'name': name})
            self.result_list.addItem(item)

        self.item_count_label.setText(f'共 {len(items)} 项')
        self.import_btn.setEnabled(len(items) > 0)
        self.status_label.setText(f'✅ 解析成功，找到 {len(items)} 项')

        # 更新全选状态
        self.select_all_cb.blockSignals(True)
        self.select_all_cb.setChecked(True)
        self.select_all_cb.blockSignals(False)

    def _toggle_select_all(self, state):
        """全选/取消全选"""
        check_state = Qt.CheckState.Checked if state == 2 else Qt.CheckState.Unchecked
        for i in range(self.result_list.count()):
            self.result_list.item(i).setCheckState(check_state)

    def _toggle_raw_preview(self):
        """切换原始内容预览"""
        if self.raw_preview.isVisible():
            self.raw_preview.hide()
            self.toggle_raw_btn.setText('📄 查看原始内容')
        else:
            if self._parse_result and self._parse_result.get('raw'):
                self.raw_preview.setPlainText(self._parse_result['raw'][:5000])
            self.raw_preview.show()
            self.toggle_raw_btn.setText('📄 隐藏原始内容')

    def _do_import(self):
        """执行导入"""
        repos = []
        sources = []

        # 收集勾选的项
        if self._parse_result['type'] == 'repository' and self._parse_result['data']:
            repo = self._parse_result['data']
            # 过滤勾选的源
            selected_sources = []
            for i in range(self.result_list.count()):
                item = self.result_list.item(i)
                if item.checkState() == Qt.CheckState.Checked:
                    data = item.data(Qt.ItemDataRole.UserRole)
                    src = ConvertedSource(
                        name=data['name'].split('  (')[0].replace('  ☑  ', '').strip(),
                        url=data['url'],
                        source_type='json',
                        repo_name=repo.name
                    )
                    selected_sources.append(src)
            if selected_sources:
                repo.sources = selected_sources
                repos.append(repo)

        elif self._parse_result['type'] in ('source', 'live') and self._parse_result['data']:
            all_sources = self._parse_result['data']
            if not isinstance(all_sources, list):
                all_sources = [all_sources]
            for i in range(self.result_list.count()):
                item = self.result_list.item(i)
                if item.checkState() == Qt.CheckState.Checked:
                    if i < len(all_sources):
                        sources.append(all_sources[i])

        if not repos and not sources:
            self.status_label.setText('⚠️ 请至少选择一项')
            return

        # 如果有 state，直接写入
        if self.state:
            self._write_to_state(repos, sources)

        # 发射信号
        self.converted.emit(repos, sources)
        self.status_label.setText(f'✅ 已导入 {len(repos)} 个仓库, {len(sources)} 个源')

        # 延迟关闭
        QTimer.singleShot(800, self.accept)

    def _write_to_state(self, repos, sources):
        """写入 AppState"""
        if not self.state:
            return

        # 导入仓库
        for repo in repos:
            # 去重
            existing_urls = {r.url for r in self.state.repositories}
            if repo.url not in existing_urls:
                from models import Repository as RepoModel
                new_repo = RepoModel(
                    name=repo.name,
                    url=repo.url,
                    enabled=True,
                    source_count=len(repo.sources)
                )
                self.state.repositories.append(new_repo)

            # 导入仓库下的源
            for src in repo.sources:
                existing_src_urls = {s.url for s in self.state.sources}
                if src.url not in existing_src_urls:
                    from models import SourceInfo
                    new_src = SourceInfo(
                        name=src.name,
                        url=src.url,
                        source_type=src.source_type,
                        enabled=True,
                        repo_name=repo.name
                    )
                    self.state.sources.append(new_src)

        # 导入独立源
        for src in sources:
            existing_src_urls = {s.url for s in self.state.sources}
            if src.url not in existing_src_urls:
                from models import SourceInfo
                new_src = SourceInfo(
                    name=src.name,
                    url=src.url,
                    source_type=src.source_type,
                    source_kind=src.source_kind,
                    enabled=True
                )
                self.state.sources.append(new_src)

        self.state.save()


# ============================================================
#  快捷方法：直接粘贴导入（无需对话框）
# ============================================================

def quick_paste_import(state, parent=None) -> bool:
    """
    快捷粘贴导入 — 从剪贴板读取链接，直接弹确认框
    返回 True 如果成功导入
    """
    clipboard = QApplication.clipboard()
    url = clipboard.text().strip()

    if not url or not url.startswith('http'):
        return False

    link_type = guess_link_type(url)
    if link_type == 'video':
        return False

    result = fetch_and_parse_url(url)
    if result['error']:
        return False

    repos = []
    sources = []

    if result['type'] == 'repository' and result['data']:
        repos.append(result['data'])
    elif result['type'] in ('source', 'live') and result['data']:
        if isinstance(result['data'], list):
            sources.extend(result['data'])
        else:
            sources.append(result['data'])

    if not repos and not sources:
        return False

    # 弹确认框
    count = sum(len(r.sources) for r in repos) + len(sources)
    reply = QMessageBox.question(
        parent,
        '🔗 导入确认',
        f'检测到链接，解析出 {count} 项:\n\n'
        + '\n'.join(f'📦 仓库 {r.name}: {len(r.sources)} 个源' for r in repos)
        + '\n'.join(f'📡 源 {s.name}' for s in sources[:5])
        + ('\n...' if len(sources) > 5 else '')
        + '\n\n是否导入？',
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )

    if reply == QMessageBox.StandardButton.Yes:
        dialog = PasteLinkDialog(parent=parent, state=state)
        dialog._parse_result = result
        dialog._write_to_state(repos, sources)
        return True

    return False
