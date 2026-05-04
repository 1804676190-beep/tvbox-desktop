#!/usr/bin/env python3
"""TVBox Desktop — 主窗口 UI"""

import os
import sys
import json
from functools import partial

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QLabel, QLineEdit, QComboBox, QTabWidget,
    QStackedWidget, QScrollArea, QGridLayout, QFrame, QToolBar,
    QMenuBar, QMenu, QStatusBar, QDialog, QDialogButtonBox,
    QFormLayout, QListWidget, QListWidgetItem, QFileDialog,
    QMessageBox, QProgressBar, QSlider, QCheckBox, QSpinBox,
    QApplication, QSizePolicy, QTextEdit
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSize, QUrl, QByteArray
)
from PyQt6.QtGui import (
    QFont, QPixmap, QIcon, QAction, QPainter, QColor, QPen,
    QDesktopServices, QPalette
)

from core.models import (
    VideoItem, LiveChannel, SourceInfo, Repository,
    CloudDriveConfig, Category, AppState
)
from core.source_manager import SourceManager
from core.repository import fetch_repository, PRESET_REPOSITORIES
from core.cloud_drive import AlistClient, WebDAVClient, CloudFile
from core.media_player import MediaPlayer
from paste_link_converter import PasteLinkDialog


# ============================================================
#  异步工作线程
# ============================================================

class WorkerThread(QThread):
    """通用异步工作线程"""
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            result = self.func(*self.args, **self.kwargs)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


# ============================================================
#  异步封面图加载
# ============================================================

class CoverLoader(QThread):
    """异步加载封面图"""
    loaded = pyqtSignal(str, QPixmap)  # url, pixmap

    def __init__(self):
        super().__init__()
        self._queue = []
        self._running = False

    def enqueue(self, url: str, label: QLabel):
        if not url:
            return
        self._queue.append((url, label))
        if not self._running:
            self._running = True
            self.start()

    def run(self):
        import requests
        while self._queue:
            url, label = self._queue.pop(0)
            try:
                resp = requests.get(url, timeout=10, verify=False)
                if resp.status_code == 200:
                    pixmap = QPixmap()
                    pixmap.loadFromData(QByteArray(resp.content))
                    if not pixmap.isNull():
                        self.loaded.emit(url, pixmap)
            except Exception:
                pass
        self._running = False


# ============================================================
#  封面卡片组件
# ============================================================

class VideoCard(QFrame):
    """视频封面卡片"""
    clicked = pyqtSignal(VideoItem)

    def __init__(self, video: VideoItem, cover_loader: CoverLoader, parent=None):
        super().__init__(parent)
        self.video = video
        self.cover_loader = cover_loader
        self.setFixedSize(160, 240)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            VideoCard {
                background: #1a1a2e;
                border: 1px solid #2a2a4e;
                border-radius: 8px;
            }
            VideoCard:hover {
                border-color: #5a5aaa;
                background: #22224a;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # 封面图
        self.cover_label = QLabel()
        self.cover_label.setFixedSize(148, 180)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setStyleSheet("""
            QLabel {
                background: #0f0f1a;
                border-radius: 4px;
                color: #555;
                font-size: 24px;
            }
        """)
        self.cover_label.setText('🎬')
        layout.addWidget(self.cover_label)

        # 标题
        title_label = QLabel(video.name)
        title_label.setStyleSheet("color: #eee; font-size: 12px; font-weight: bold;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setWordWrap(True)
        title_label.setMaximumHeight(32)
        layout.addWidget(title_label)

        # 标签
        tags = []
        if video.year:
            tags.append(video.year)
        if video.group:
            tags.append(video.group)
        if tags:
            tag_label = QLabel(' · '.join(tags))
            tag_label.setStyleSheet("color: #888; font-size: 10px;")
            tag_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(tag_label)

        # 异步加载封面
        if video.pic:
            self.cover_loader.enqueue(video.pic, self.cover_label)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.video)
        super().mousePressEvent(event)


# ============================================================
#  详情页
# ============================================================

class DetailPage(QWidget):
    """视频详情页"""
    play_requested = pyqtSignal(str, str, int)  # url, title, source_index
    back_requested = pyqtSignal()

    def __init__(self, cover_loader: CoverLoader, parent=None):
        super().__init__(parent)
        self.video = None
        self.cover_loader = cover_loader
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 返回按钮
        back_btn = QPushButton('← 返回')
        back_btn.setFixedWidth(80)
        back_btn.setStyleSheet("""
            QPushButton {
                background: #2a2a4e;
                border: 1px solid #3a3a6e;
                border-radius: 4px;
                padding: 6px 12px;
                color: #eee;
            }
            QPushButton:hover { background: #3a3a6e; }
        """)
        back_btn.clicked.connect(self.back_requested.emit)
        layout.addWidget(back_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # 信息区
        info_row = QHBoxLayout()

        # 封面
        self.cover_label = QLabel()
        self.cover_label.setFixedSize(200, 280)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setStyleSheet("""
            QLabel {
                background: #0f0f1a;
                border-radius: 8px;
                color: #555;
                font-size: 48px;
            }
        """)
        self.cover_label.setText('🎬')
        info_row.addWidget(self.cover_label)

        # 文字信息
        info_col = QVBoxLayout()

        self.title_label = QLabel()
        self.title_label.setStyleSheet("color: #eee; font-size: 20px; font-weight: bold;")
        info_col.addWidget(self.title_label)

        self.meta_label = QLabel()
        self.meta_label.setStyleSheet("color: #aaa; font-size: 13px;")
        self.meta_label.setWordWrap(True)
        info_col.addWidget(self.meta_label)

        self.desc_label = QLabel()
        self.desc_label.setStyleSheet("color: #888; font-size: 12px;")
        self.desc_label.setWordWrap(True)
        self.desc_label.setMaximumHeight(80)
        info_col.addWidget(self.desc_label)

        info_col.addStretch()
        info_row.addLayout(info_col, 1)
        layout.addLayout(info_row)

        # 线路选择
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel('线路:'))
        self.source_combo = QComboBox()
        self.source_combo.setStyleSheet("""
            QComboBox {
                background: #1a1a2e;
                border: 1px solid #333;
                border-radius: 4px;
                padding: 6px 12px;
                color: #eee;
                min-width: 150px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #1a1a2e;
                border: 1px solid #333;
                color: #eee;
                selection-background-color: #3a3a6e;
            }
        """)
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        source_row.addWidget(self.source_combo)
        source_row.addStretch()
        layout.addLayout(source_row)

        # 剧集网格
        self.episodes_scroll = QScrollArea()
        self.episodes_scroll.setWidgetResizable(True)
        self.episodes_widget = QWidget()
        self.episodes_layout = QGridLayout(self.episodes_widget)
        self.episodes_layout.setSpacing(8)
        self.episodes_scroll.setWidget(self.episodes_widget)
        self.episodes_scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QWidget { background: transparent; }
        """)
        layout.addWidget(self.episodes_scroll, 1)

    def set_video(self, video: VideoItem):
        """设置视频信息"""
        self.video = video

        self.title_label.setText(video.name)

        meta_parts = []
        if video.year:
            meta_parts.append(f'年份: {video.year}')
        if video.area:
            meta_parts.append(f'地区: {video.area}')
        if video.type_name:
            meta_parts.append(f'类型: {video.type_name}')
        if video.director:
            meta_parts.append(f'导演: {video.director}')
        if video.actor:
            meta_parts.append(f'主演: {video.actor}')
        self.meta_label.setText(' | '.join(meta_parts))

        desc = video.description
        if desc:
            # 清理 HTML 标签
            import re
            desc = re.sub(r'<[^>]+>', '', desc).strip()
        self.desc_label.setText(desc[:200] if desc else '')

        # 加载封面
        self.cover_label.setText('🎬')
        if video.pic:
            self.cover_loader.enqueue(video.pic, self.cover_label)

        # 线路选择
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        for src in video.play_sources:
            self.source_combo.addItem(src['name'])
        self.source_combo.blockSignals(False)

        # 显示第一条线路的剧集
        if video.episodes:
            self._show_episodes(video.episodes)
        elif video.play_sources:
            self._show_episodes(video.play_sources[0]['episodes'])

    def _on_source_changed(self, index: int):
        """线路切换"""
        if self.video and 0 <= index < len(self.video.play_sources):
            episodes = self.video.play_sources[index]['episodes']
            self.video.episodes = episodes
            self._show_episodes(episodes)

    def _show_episodes(self, episodes: list):
        """显示剧集网格"""
        # 清空
        while self.episodes_layout.count():
            item = self.episodes_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        cols = 8
        for i, ep in enumerate(episodes):
            btn = QPushButton(ep['name'])
            btn.setFixedSize(90, 36)
            btn.setStyleSheet("""
                QPushButton {
                    background: #1a1a2e;
                    border: 1px solid #333;
                    border-radius: 4px;
                    color: #eee;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background: #3a3a6e;
                    border-color: #5a5aaa;
                }
            """)
            btn.clicked.connect(partial(self._play_episode, i))
            self.episodes_layout.addWidget(btn, i // cols, i % cols)

        # 填充剩余空格
        total = len(episodes)
        remainder = total % cols
        if remainder:
            for j in range(cols - remainder):
                spacer = QWidget()
                spacer.setFixedSize(90, 36)
                self.episodes_layout.addWidget(spacer, total // cols, remainder + j)

    def _play_episode(self, index: int):
        """播放指定剧集"""
        if self.video and self.video.episodes and index < len(self.video.episodes):
            ep = self.video.episodes[index]
            source_idx = self.source_combo.currentIndex()
            self.play_requested.emit(ep['url'], f"{self.video.name} - {ep['name']}", source_idx)


# ============================================================
#  直播页
# ============================================================

class LivePage(QWidget):
    """直播频道页"""
    play_requested = pyqtSignal(str, str)  # url, title

    def __init__(self, parent=None):
        super().__init__(parent)
        self._channels = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 左侧分组列表
        self.group_list = QListWidget()
        self.group_list.setFixedWidth(150)
        self.group_list.setStyleSheet("""
            QListWidget {
                background: #16162a;
                border: none;
                border-right: 1px solid #333;
                color: #eee;
                font-size: 13px;
            }
            QListWidget::item {
                padding: 10px 12px;
                border-bottom: 1px solid #222;
            }
            QListWidget::item:selected {
                background: #3a3a6e;
            }
            QListWidget::item:hover {
                background: #2a2a4e;
            }
        """)
        self.group_list.currentTextChanged.connect(self._on_group_changed)
        layout.addWidget(self.group_list)

        # 右侧频道列表
        self.channel_list = QListWidget()
        self.channel_list.setStyleSheet("""
            QListWidget {
                background: #0f0f1a;
                border: none;
                color: #eee;
                font-size: 13px;
            }
            QListWidget::item {
                padding: 10px 16px;
                border-bottom: 1px solid #1a1a2e;
            }
            QListWidget::item:selected {
                background: #2a2a4e;
            }
            QListWidget::item:hover {
                background: #1a1a3a;
            }
        """)
        self.channel_list.itemDoubleClicked.connect(self._on_channel_double_click)
        layout.addWidget(self.channel_list, 1)

    def set_channels(self, channels: list):
        """设置直播频道"""
        self._channels = channels

        # 获取分组
        groups = []
        seen = set()
        for ch in channels:
            g = ch.group or '默认'
            if g not in seen:
                groups.append(g)
                seen.add(g)

        self.group_list.clear()
        self.group_list.addItems(groups)
        if groups:
            self.group_list.setCurrentRow(0)

    def _on_group_changed(self, group_name: str):
        """分组切换"""
        self.channel_list.clear()
        for ch in self._channels:
            if (ch.group or '默认') == group_name:
                item = QListWidgetItem(f"📺  {ch.name}")
                item.setData(Qt.ItemDataRole.UserRole, ch)
                self.channel_list.addItem(item)

    def _on_channel_double_click(self, item: QListWidgetItem):
        """双击播放频道"""
        ch = item.data(Qt.ItemDataRole.UserRole)
        if ch and ch.urls:
            self.play_requested.emit(ch.urls[0], ch.name)


# ============================================================
#  网盘页
# ============================================================

class CloudDrivePage(QWidget):
    """网盘浏览页"""
    play_requested = pyqtSignal(str, str)  # url, title

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self._client = None
        self._current_path = "/"
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 顶部工具栏
        toolbar = QHBoxLayout()

        toolbar.addWidget(QLabel('网盘:'))
        self.drive_combo = QComboBox()
        self.drive_combo.setStyleSheet("""
            QComboBox {
                background: #1a1a2e;
                border: 1px solid #333;
                border-radius: 4px;
                padding: 6px 12px;
                color: #eee;
                min-width: 120px;
            }
        """)
        toolbar.addWidget(self.drive_combo)

        self.connect_btn = QPushButton('连接')
        self.connect_btn.clicked.connect(self._on_connect)
        toolbar.addWidget(self.connect_btn)

        toolbar.addSpacing(20)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('搜索文件...')
        self.search_input.setFixedWidth(200)
        self.search_input.returnPressed.connect(self._on_search)
        toolbar.addWidget(self.search_input)

        search_btn = QPushButton('🔍')
        search_btn.clicked.connect(self._on_search)
        toolbar.addWidget(search_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # 路径导航
        self.path_label = QLabel('/')
        self.path_label.setStyleSheet("color: #888; font-size: 12px; padding: 4px;")
        layout.addWidget(self.path_label)

        # 文件列表
        self.file_list = QListWidget()
        self.file_list.setStyleSheet("""
            QListWidget {
                background: #0f0f1a;
                border: 1px solid #222;
                border-radius: 4px;
                color: #eee;
            }
            QListWidget::item {
                padding: 8px 12px;
                border-bottom: 1px solid #1a1a2e;
            }
            QListWidget::item:selected {
                background: #2a2a4e;
            }
            QListWidget::item:hover {
                background: #1a1a3a;
            }
        """)
        self.file_list.itemDoubleClicked.connect(self._on_file_double_click)
        layout.addWidget(self.file_list, 1)

        # 刷新网盘列表
        self._refresh_drives()

    def _refresh_drives(self):
        """刷新网盘下拉列表"""
        self.drive_combo.clear()
        for drive in self.state.cloud_drives:
            self.drive_combo.addItem(f"{drive.name} ({drive.drive_type})", drive)

    def _on_connect(self):
        """连接网盘"""
        idx = self.drive_combo.currentIndex()
        if idx < 0:
            return
        drive = self.drive_combo.currentData()
        if not drive:
            return

        if drive.drive_type == 'alist':
            self._client = AlistClient(drive.url)
            if drive.token:
                self._client.set_token(drive.token)
            elif drive.username and drive.password:
                if not self._client.login(drive.username, drive.password):
                    QMessageBox.warning(self, '连接失败', 'Alist 登录失败，请检查账号密码')
                    return
        elif drive.drive_type == 'webdav':
            self._client = WebDAVClient(drive.url, drive.username, drive.password)
        else:
            return

        self._current_path = '/'
        self._browse('/')

    def _browse(self, path: str):
        """浏览目录"""
        if not self._client:
            return
        self._current_path = path
        self.path_label.setText(f'📁 {path}')
        self.file_list.clear()

        files = self._client.list_dir(path)

        # 排序: 目录在前，文件在后，按名称排序
        dirs = sorted([f for f in files if f.is_dir], key=lambda x: x.name.lower())
        file_items = sorted([f for f in files if not f.is_dir], key=lambda x: x.name.lower())

        # 返回上级
        if path != '/':
            item = QListWidgetItem('📁  ..')
            item.setData(Qt.ItemDataRole.UserRole, {'type': 'back', 'path': os.path.dirname(path.rstrip('/')) or '/'})
            self.file_list.addItem(item)

        for f in dirs:
            item = QListWidgetItem(f'📁  {f.name}')
            item.setData(Qt.ItemDataRole.UserRole, {'type': 'dir', 'file': f})
            self.file_list.addItem(item)

        for f in file_items:
            icon = '🎬' if f.is_video else '🎵' if f.is_media else '📄'
            size_str = f.size_str if f.size else ''
            item = QListWidgetItem(f'{icon}  {f.name}  {size_str}')
            item.setData(Qt.ItemDataRole.UserRole, {'type': 'file', 'file': f})

            if f.is_video:
                item.setForeground(QColor('#5a8aaa'))
            self.file_list.addItem(item)

    def _on_file_double_click(self, item: QListWidgetItem):
        """双击文件/目录"""
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return

        if data['type'] == 'back':
            self._browse(data['path'])
        elif data['type'] == 'dir':
            f = data['file']
            path = f.path if f.path.startswith('/') else f"{self._current_path.rstrip('/')}/{f.name}"
            self._browse(path)
        elif data['type'] == 'file':
            f = data['file']
            if f.is_video and self._client:
                url = self._client.get_download_url(f.path)
                self.play_requested.emit(url, f.name)

    def _on_search(self):
        """搜索文件"""
        keyword = self.search_input.text().strip()
        if not keyword or not self._client:
            return

        if isinstance(self._client, AlistClient):
            results = self._client.search(keyword, self._current_path)
            self.file_list.clear()
            for f in results:
                icon = '🎬' if f.is_video else '📄'
                item = QListWidgetItem(f'{icon}  {f.path}')
                item.setData(Qt.ItemDataRole.UserRole, {'type': 'file', 'file': f})
                if f.is_video:
                    item.setForeground(QColor('#5a8aaa'))
                self.file_list.addItem(item)
        else:
            QMessageBox.information(self, '提示', 'WebDAV 暂不支持搜索')


# ============================================================
#  源管理对话框
# ============================================================

class SourceDialog(QDialog):
    """订阅源管理对话框"""

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle('📡 管理订阅源')
        self.setMinimumSize(500, 400)
        self.setStyleSheet(parent.STYLE if parent and hasattr(parent, 'STYLE') else '')
        self._setup_ui()
        self._refresh_list()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self.source_list = QListWidget()
        layout.addWidget(self.source_list)

        btn_row = QHBoxLayout()
        add_btn = QPushButton('➕ 手动添加')
        add_btn.clicked.connect(self._add_source)
        btn_row.addWidget(add_btn)

        preset_btn = QPushButton('📋 预设源')
        preset_btn.clicked.connect(self._add_presets)
        btn_row.addWidget(preset_btn)

        del_btn = QPushButton('🗑️ 删除选中')
        del_btn.clicked.connect(self._delete_source)
        btn_row.addWidget(del_btn)

        btn_row.addStretch()

        close_btn = QPushButton('关闭')
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

    def _refresh_list(self):
        self.source_list.clear()
        for src in self.state.sources:
            status = '✅' if src.enabled else '❌'
            repo = f' [{src.repo_name}]' if src.repo_name else ''
            item = QListWidgetItem(f'{status} {src.name} ({src.source_type}){repo}')
            item.setData(Qt.ItemDataRole.UserRole, src)
            self.source_list.addItem(item)

    def _add_source(self):
        """手动添加源"""
        from PyQt6.QtWidgets import QInputDialog
        name, ok1 = QInputDialog.getText(self, '添加源', '源名称:')
        if not ok1 or not name:
            return
        url, ok2 = QInputDialog.getText(self, '添加源', '源 URL:')
        if not ok2 or not url:
            return
        self.state.sources.append(SourceInfo(name=name, url=url))
        self.state.save()
        self._refresh_list()

    def _add_presets(self):
        """添加预设源"""
        # TVBox 内置预设源
        presets = [
            SourceInfo(name='饭太硬源', url='https://fantaiying.github.io/rrtv/tv/fta.json', repo_name='饭太硬'),
            SourceInfo(name='OK猫源', url='https://ok321.top/tv/ok.json', repo_name='OK猫'),
            SourceInfo(name='小米影视源', url='https://raw.githubusercontent.com/xiaomi12345/xiaomitv/main/tv/1.json', repo_name='小米影视'),
        ]
        existing = {s.url for s in self.state.sources}
        added = 0
        for p in presets:
            if p.url not in existing:
                self.state.sources.append(p)
                added += 1
        if added:
            self.state.save()
            self._refresh_list()
            QMessageBox.information(self, '预设源', f'已添加 {added} 个预设源')
        else:
            QMessageBox.information(self, '预设源', '所有预设源已存在')

    def _delete_source(self):
        item = self.source_list.currentItem()
        if not item:
            return
        src = item.data(Qt.ItemDataRole.UserRole)
        self.state.sources = [s for s in self.state.sources if s.url != src.url]
        self.state.save()
        self._refresh_list()


# ============================================================
#  仓库管理对话框
# ============================================================

class RepoDialog(QDialog):
    """仓库管理对话框"""

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self._worker = None
        self.setWindowTitle('🏪 管理仓库')
        self.setMinimumSize(550, 450)
        self.setStyleSheet(parent.STYLE if parent and hasattr(parent, 'STYLE') else '')
        self._setup_ui()
        self._refresh_list()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self.repo_list = QListWidget()
        layout.addWidget(self.repo_list)

        btn_row = QHBoxLayout()
        add_btn = QPushButton('➕ 添加仓库')
        add_btn.clicked.connect(self._add_repo)
        btn_row.addWidget(add_btn)

        preset_btn = QPushButton('📋 预设仓库')
        preset_btn.clicked.connect(self._add_presets)
        btn_row.addWidget(preset_btn)

        fetch_btn = QPushButton('🔄 拉取选中')
        fetch_btn.clicked.connect(self._fetch_selected)
        btn_row.addWidget(fetch_btn)

        paste_btn = QPushButton('🔗 粘贴链接')
        paste_btn.setToolTip('粘贴仓库链接，自动解析并导入')
        paste_btn.clicked.connect(self._paste_link)
        btn_row.addWidget(paste_btn)

        del_btn = QPushButton('🗑️ 删除')
        del_btn.clicked.connect(self._delete_repo)
        btn_row.addWidget(del_btn)

        btn_row.addStretch()
        close_btn = QPushButton('关闭')
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

        # 状态
        self.status_label = QLabel('')
        self.status_label.setStyleSheet("color: #888;")
        layout.addWidget(self.status_label)

    def _refresh_list(self):
        self.repo_list.clear()
        for repo in self.state.repositories:
            status = '✅' if repo.enabled else '❌'
            item = QListWidgetItem(f'{status} {repo.name}  ({repo.source_count} 个源)')
            item.setData(Qt.ItemDataRole.UserRole, repo)
            self.repo_list.addItem(item)

    def _add_repo(self):
        from PyQt6.QtWidgets import QInputDialog
        url, ok = QInputDialog.getText(self, '添加仓库', '仓库 URL:')
        if ok and url:
            name, ok2 = QInputDialog.getText(self, '添加仓库', '仓库名称:', text=url.split('/')[-1].replace('.json', ''))
            if ok2:
                repo = Repository(name=name or '未命名', url=url)
                self.state.repositories.append(repo)
                self.state.save()
                self._refresh_list()

    def _add_presets(self):
        existing = {r.url for r in self.state.repositories}
        added = 0
        for p in PRESET_REPOSITORIES:
            if p['url'] not in existing:
                self.state.repositories.append(Repository(name=p['name'], url=p['url']))
                added += 1
        if added:
            self.state.save()
            self._refresh_list()
            QMessageBox.information(self, '预设仓库', f'已添加 {added} 个预设仓库')
        else:
            QMessageBox.information(self, '预设仓库', '所有预设仓库已存在')

    def _fetch_selected(self):
        item = self.repo_list.currentItem()
        if not item:
            return
        repo = item.data(Qt.ItemDataRole.UserRole)
        self.status_label.setText(f'🔄 正在拉取 {repo.name}...')
        self.setEnabled(False)

        self._worker = WorkerThread(fetch_repository, repo.url)
        self._worker.finished.connect(lambda sources: self._on_fetch_done(repo, sources))
        self._worker.error.connect(lambda e: self._on_fetch_error(e))
        self._worker.start()

    def _on_fetch_done(self, repo, sources):
        self.setEnabled(True)
        if sources:
            existing = {s.url for s in self.state.sources}
            added = 0
            for src in sources:
                if src.url not in existing:
                    self.state.sources.append(src)
                    added += 1
            repo.source_count = len(sources)
            self.state.save()
            self.status_label.setText(f'✅ {repo.name}: 导入 {added} 个源 (共 {len(sources)} 个)')
        else:
            self.status_label.setText(f'❌ {repo.name}: 未解析到源')
        self._refresh_list()

    def _on_fetch_error(self, error):
        self.setEnabled(True)
        self.status_label.setText(f'❌ 拉取失败: {error}')

    def _paste_link(self):
        """粘贴链接导入"""
        dialog = PasteLinkDialog(parent=self, state=self.state)
        dialog.converted.connect(self._on_link_imported)
        dialog.exec()

    def _on_link_imported(self, repos, sources):
        """链接导入完成"""
        self._refresh_list()
        total = sum(len(r.sources) for r in repos) + len(sources)
        self.status_label.setText(f'✅ 已导入 {total} 项')

    def _delete_repo(self):
        item = self.repo_list.currentItem()
        if not item:
            return
        repo = item.data(Qt.ItemDataRole.UserRole)
        self.state.repositories = [r for r in self.state.repositories if r.url != repo.url]
        self.state.save()
        self._refresh_list()


# ============================================================
#  网盘管理对话框
# ============================================================

class CloudDriveDialog(QDialog):
    """网盘配置对话框"""

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle('☁️ 管理网盘')
        self.setMinimumSize(500, 350)
        self.setStyleSheet(parent.STYLE if parent and hasattr(parent, 'STYLE') else '')
        self._setup_ui()
        self._refresh_list()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self.drive_list = QListWidget()
        layout.addWidget(self.drive_list)

        form = QFormLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText('网盘名称')
        form.addRow('名称:', self.name_input)

        self.type_combo = QComboBox()
        self.type_combo.addItems(['alist', 'webdav'])
        form.addRow('类型:', self.type_combo)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText('http://localhost:5244')
        form.addRow('地址:', self.url_input)

        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText('用户名')
        form.addRow('用户名:', self.user_input)

        self.pass_input = QLineEdit()
        self.pass_input.setPlaceholderText('密码')
        self.pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow('密码:', self.pass_input)

        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText('Token (Alist 可选)')
        form.addRow('Token:', self.token_input)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        add_btn = QPushButton('➕ 添加')
        add_btn.clicked.connect(self._add_drive)
        btn_row.addWidget(add_btn)

        del_btn = QPushButton('🗑️ 删除')
        del_btn.clicked.connect(self._delete_drive)
        btn_row.addWidget(del_btn)

        btn_row.addStretch()
        close_btn = QPushButton('关闭')
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

    def _refresh_list(self):
        self.drive_list.clear()
        for drive in self.state.cloud_drives:
            item = QListWidgetItem(f"{drive.name} ({drive.drive_type}) {drive.url}")
            item.setData(Qt.ItemDataRole.UserRole, drive)
            self.drive_list.addItem(item)

    def _add_drive(self):
        name = self.name_input.text().strip()
        url = self.url_input.text().strip()
        if not name or not url:
            QMessageBox.warning(self, '提示', '请填写名称和地址')
            return
        drive = CloudDriveConfig(
            name=name,
            drive_type=self.type_combo.currentText(),
            url=url,
            username=self.user_input.text().strip(),
            password=self.pass_input.text().strip(),
            token=self.token_input.text().strip(),
        )
        self.state.cloud_drives.append(drive)
        self.state.save()
        self._refresh_list()
        self.name_input.clear()
        self.url_input.clear()
        self.user_input.clear()
        self.pass_input.clear()
        self.token_input.clear()

    def _delete_drive(self):
        item = self.drive_list.currentItem()
        if not item:
            return
        drive = item.data(Qt.ItemDataRole.UserRole)
        self.state.cloud_drives = [d for d in self.state.cloud_drives if d.url != drive.url]
        self.state.save()
        self._refresh_list()


# ============================================================
#  搜索页
# ============================================================

class SearchPage(QWidget):
    """搜索结果页"""
    detail_requested = pyqtSignal(str, str)  # api_url, vod_id

    def __init__(self, cover_loader: CoverLoader, parent=None):
        super().__init__(parent)
        self.cover_loader = cover_loader
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.title_label = QLabel('搜索结果')
        self.title_label.setStyleSheet("color: #aaa; font-size: 14px; margin-bottom: 8px;")
        layout.addWidget(self.title_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.grid_layout = QGridLayout(self.scroll_content)
        self.grid_layout.setSpacing(12)
        self.scroll.setWidget(self.scroll_content)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        layout.addWidget(self.scroll, 1)

        self.empty_label = QLabel('🔍 输入关键词开始搜索')
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: #555; font-size: 16px;")
        layout.addWidget(self.empty_label)

    def show_results(self, items: list, api_url: str):
        """显示搜索结果"""
        # 清空
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not items:
            self.empty_label.setText('😔 未找到结果')
            self.empty_label.show()
            self.title_label.setText('搜索结果')
            return

        self.empty_label.hide()
        self.title_label.setText(f'搜索结果 ({len(items)} 个)')

        cols = max(1, self.width() // 172)
        for i, video in enumerate(items):
            card = VideoCard(video, self.cover_loader)
            card.clicked.connect(partial(self._on_card_clicked, api_url))
            self.grid_layout.addWidget(card, i // cols, i % cols)

    def _on_card_clicked(self, api_url: str, video: VideoItem):
        self.detail_requested.emit(api_url, video.url)

    def show_empty(self, msg: str = ''):
        self.empty_label.setText(msg or '🔍 输入关键词开始搜索')
        self.empty_label.show()


# ============================================================
#  主窗口
# ============================================================

class MainWindow(QMainWindow):
    """TVBox Desktop 主窗口"""

    STYLE = """
    QMainWindow, QWidget {
        background: #0f0f1a;
        color: #eee;
    }
    QMenuBar {
        background: #16162a;
        border-bottom: 1px solid #333;
        color: #eee;
    }
    QMenuBar::item:selected {
        background: #3a3a6e;
    }
    QMenu {
        background: #1a1a2e;
        border: 1px solid #333;
        color: #eee;
    }
    QMenu::item:selected {
        background: #3a3a6e;
    }
    QToolBar {
        background: #16162a;
        border-bottom: 1px solid #333;
        spacing: 6px;
        padding: 4px;
    }
    QStatusBar {
        background: #16162a;
        border-top: 1px solid #333;
        color: #888;
    }
    QTabWidget::pane {
        border: 1px solid #333;
        background: #0f0f1a;
    }
    QTabBar::tab {
        background: #1a1a2e;
        border: 1px solid #333;
        padding: 8px 16px;
        color: #aaa;
        margin-right: 2px;
    }
    QTabBar::tab:selected {
        background: #2a2a4e;
        color: #eee;
        border-bottom-color: #2a2a4e;
    }
    QTabBar::tab:hover {
        background: #22224a;
    }
    QScrollBar:vertical {
        background: #0f0f1a;
        width: 8px;
        border: none;
    }
    QScrollBar::handle:vertical {
        background: #333;
        border-radius: 4px;
        min-height: 30px;
    }
    QScrollBar::handle:vertical:hover {
        background: #555;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0;
    }
    QScrollBar:horizontal {
        background: #0f0f1a;
        height: 8px;
        border: none;
    }
    QScrollBar::handle:horizontal {
        background: #333;
        border-radius: 4px;
        min-width: 30px;
    }
    QLineEdit {
        background: #1a1a2e;
        border: 1px solid #333;
        border-radius: 4px;
        padding: 6px 10px;
        color: #eee;
    }
    QLineEdit:focus {
        border-color: #5a5aaa;
    }
    QComboBox {
        background: #1a1a2e;
        border: 1px solid #333;
        border-radius: 4px;
        padding: 6px 10px;
        color: #eee;
    }
    QComboBox::drop-down { border: none; }
    QComboBox QAbstractItemView {
        background: #1a1a2e;
        border: 1px solid #333;
        color: #eee;
        selection-background-color: #3a3a6e;
    }
    QPushButton {
        background: #2a2a4e;
        border: 1px solid #3a3a6e;
        border-radius: 4px;
        padding: 6px 14px;
        color: #eee;
    }
    QPushButton:hover {
        background: #3a3a6e;
        border-color: #5a5aaa;
    }
    QPushButton:pressed {
        background: #4a4a8e;
    }
    QSlider::groove:horizontal {
        background: #333;
        height: 4px;
        border-radius: 2px;
    }
    QSlider::handle:horizontal {
        background: #5a5aaa;
        width: 14px;
        height: 14px;
        margin: -5px 0;
        border-radius: 7px;
    }
    QSlider::handle:horizontal:hover {
        background: #7a7acc;
    }
    QSlider::sub-page:horizontal {
        background: #5a5aaa;
        border-radius: 2px;
    }
    QSplitter::handle {
        background: #333;
        width: 2px;
    }
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle('TVBox Desktop')
        self.resize(1280, 720)
        self.setMinimumSize(900, 600)

        # 状态
        self.state = AppState.load()
        self.source_manager = SourceManager()
        self.media_player = MediaPlayer()
        self.cover_loader = CoverLoader()
        self.cover_loader.loaded.connect(self._on_cover_loaded)
        self._cover_labels = {}  # url -> label

        # 初始化 UI
        self.setStyleSheet(self.STYLE)
        self._setup_menubar()
        self._setup_toolbar()
        self._setup_ui()
        self._setup_player()
        self._setup_statusbar()

        # 初始化源
        if self.state.sources:
            self._refresh_source_dropdown()
            QTimer.singleShot(500, self._load_current_source)

    # ----------------------------------------------------------
    #  菜单栏
    # ----------------------------------------------------------

    def _setup_menubar(self):
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu('文件')

        src_action = QAction('📡 管理订阅源', self)
        src_action.setShortcut('Ctrl+S')
        src_action.triggered.connect(self._open_source_dialog)
        file_menu.addAction(src_action)

        repo_action = QAction('🏪 管理仓库', self)
        repo_action.setShortcut('Ctrl+R')
        repo_action.triggered.connect(self._open_repo_dialog)
        file_menu.addAction(repo_action)

        cloud_action = QAction('☁️ 管理网盘', self)
        cloud_action.triggered.connect(self._open_cloud_dialog)
        file_menu.addAction(cloud_action)

        file_menu.addSeparator()

        paste_action = QAction('🔗 粘贴链接导入...', self)
        paste_action.setShortcut('Ctrl+Shift+V')
        paste_action.triggered.connect(self._open_paste_link_dialog)
        file_menu.addAction(paste_action)

        file_menu.addSeparator()

        quit_action = QAction('退出', self)
        quit_action.setShortcut('Ctrl+Q')
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # 播放菜单
        play_menu = menubar.addMenu('播放')

        open_url_action = QAction('🔗 打开网络地址', self)
        open_url_action.setShortcut('Ctrl+O')
        open_url_action.triggered.connect(self._open_url_dialog)
        play_menu.addAction(open_url_action)

        open_file_action = QAction('📂 打开本地文件', self)
        open_file_action.setShortcut('Ctrl+L')
        open_file_action.triggered.connect(self._open_local_file)
        play_menu.addAction(open_file_action)

        # 帮助菜单
        help_menu = menubar.addMenu('帮助')
        about_action = QAction('关于', self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    # ----------------------------------------------------------
    #  工具栏
    # ----------------------------------------------------------

    def _setup_toolbar(self):
        self.toolbar = QToolBar()
        self.toolbar.setMovable(False)
        self.addToolBar(self.toolbar)

        # 源选择
        self.toolbar.addWidget(QLabel('📡 源:'))
        self.source_combo = QComboBox()
        self.source_combo.setMinimumWidth(180)
        self.source_combo.currentIndexChanged.connect(self._on_source_selected)
        self.toolbar.addWidget(self.source_combo)

        self.toolbar.addSeparator()

        # 搜索
        self.toolbar.addWidget(QLabel('🔍'))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('搜索影视...')
        self.search_input.setFixedWidth(250)
        self.search_input.returnPressed.connect(self._do_search)
        self.toolbar.addWidget(self.search_input)

        search_btn = QPushButton('搜索')
        search_btn.clicked.connect(self._do_search)
        self.toolbar.addWidget(search_btn)

        self.toolbar.addSeparator()

        # 工具按钮
        refresh_btn = QPushButton('🔄 刷新源')
        refresh_btn.clicked.connect(self._load_current_source)
        self.toolbar.addWidget(refresh_btn)

        repo_btn = QPushButton('🏪 仓库')
        repo_btn.clicked.connect(self._open_repo_dialog)
        self.toolbar.addWidget(repo_btn)

        cloud_btn = QPushButton('☁️ 网盘')
        cloud_btn.clicked.connect(self._open_cloud_dialog)
        self.toolbar.addWidget(cloud_btn)

        paste_btn = QPushButton('🔗 粘贴链接')
        paste_btn.setToolTip('粘贴链接自动识别并导入仓库/源')
        paste_btn.clicked.connect(self._open_paste_link_dialog)
        self.toolbar.addWidget(paste_btn)

    # ----------------------------------------------------------
    #  主界面
    # ----------------------------------------------------------

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 左右分栏
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧面板
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # 标签页切换
        self.left_tabs = QTabWidget()
        self.left_tabs.setTabPosition(QTabWidget.TabPosition.North)

        # 首页
        self.home_page = self._create_home_page()
        self.left_tabs.addTab(self.home_page, '🏠 首页')

        # 搜索页
        self.search_page = SearchPage(self.cover_loader)
        self.search_page.detail_requested.connect(self._load_detail)
        self.left_tabs.addTab(self.search_page, '🔍 搜索')

        # 直播页
        self.live_page = LivePage()
        self.live_page.play_requested.connect(self._play_url)
        self.left_tabs.addTab(self.live_page, '📺 直播')

        # 网盘页
        self.cloud_page = CloudDrivePage(self.state)
        self.cloud_page.play_requested.connect(self._play_url)
        self.left_tabs.addTab(self.cloud_page, '☁️ 网盘')

        # 收藏页
        self.fav_page = self._create_list_page('favorites')
        self.left_tabs.addTab(self.fav_page, '⭐ 收藏')

        # 历史页
        self.history_page = self._create_list_page('history')
        self.left_tabs.addTab(self.fav_page, '📜 历史')
        # 修正: 用 history_page
        self.left_tabs.removeTab(self.left_tabs.count() - 1)
        self.left_tabs.addTab(self.history_page, '📜 历史')

        left_layout.addWidget(self.left_tabs)
        self.splitter.addWidget(left_panel)

        # 右侧播放器
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # 播放器区域
        self.player_container = QWidget()
        self.player_container.setMinimumSize(640, 360)
        self.player_container.setStyleSheet("background: #000;")
        right_layout.addWidget(self.player_container, 1)

        # 详情页（默认隐藏，覆盖在播放器上方）
        self.detail_page = DetailPage(self.cover_loader)
        self.detail_page.play_requested.connect(self._play_episode)
        self.detail_page.back_requested.connect(self._hide_detail)
        self.detail_page.hide()
        right_layout.addWidget(self.detail_page)

        # 控制栏
        self.control_bar = self._create_control_bar()
        right_layout.addWidget(self.control_bar)

        self.splitter.addWidget(right_panel)
        self.splitter.setSizes([400, 880])
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)

        main_layout.addWidget(self.splitter)

    def _create_home_page(self) -> QWidget:
        """创建首页"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)

        self.home_scroll = QScrollArea()
        self.home_scroll.setWidgetResizable(True)
        self.home_content = QWidget()
        self.home_grid = QGridLayout(self.home_content)
        self.home_grid.setSpacing(12)
        self.home_scroll.setWidget(self.home_content)
        self.home_scroll.setStyleSheet("QScrollArea { border: none; }")
        layout.addWidget(self.home_scroll, 1)

        self.home_status = QLabel('选择一个源开始浏览')
        self.home_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.home_status.setStyleSheet("color: #555; font-size: 14px;")
        layout.addWidget(self.home_status)

        return page

    def _create_list_page(self, list_type: str) -> QWidget:
        """创建收藏/历史页"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        grid = QGridLayout(content)
        grid.setSpacing(12)
        scroll.setWidget(content)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        layout.addWidget(scroll, 1)

        # 保存引用以便刷新
        if list_type == 'favorites':
            self._fav_grid = grid
            self._fav_content = content
        else:
            self._hist_grid = grid
            self._hist_content = content

        return page

    def _create_control_bar(self) -> QWidget:
        """创建播放控制栏"""
        bar = QWidget()
        bar.setFixedHeight(60)
        bar.setStyleSheet("background: #16162a; border-top: 1px solid #333;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(12)

        # 播放控制按钮
        btn_style = """
            QPushButton {
                background: transparent;
                border: none;
                color: #aaa;
                font-size: 18px;
                padding: 4px 8px;
            }
            QPushButton:hover { color: #eee; }
        """

        self.prev_btn = QPushButton('⏮')
        self.prev_btn.setStyleSheet(btn_style)
        self.prev_btn.clicked.connect(self._play_prev)
        layout.addWidget(self.prev_btn)

        self.play_btn = QPushButton('▶')
        self.play_btn.setStyleSheet(btn_style)
        self.play_btn.clicked.connect(self._toggle_pause)
        layout.addWidget(self.play_btn)

        self.next_btn = QPushButton('⏭')
        self.next_btn.setStyleSheet(btn_style)
        self.next_btn.clicked.connect(self._play_next)
        layout.addWidget(self.next_btn)

        self.stop_btn = QPushButton('⏹')
        self.stop_btn.setStyleSheet(btn_style)
        self.stop_btn.clicked.connect(self._stop_playback)
        layout.addWidget(self.stop_btn)

        # 进度条
        self.progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setRange(0, 1000)
        self.progress_slider.sliderMoved.connect(self._on_seek)
        layout.addWidget(self.progress_slider, 1)

        # 时间标签
        self.time_label = QLabel('00:00 / 00:00')
        self.time_label.setStyleSheet("color: #aaa; font-size: 12px;")
        self.time_label.setFixedWidth(120)
        layout.addWidget(self.time_label)

        # 音量
        vol_label = QPushButton('🔊')
        vol_label.setStyleSheet(btn_style)
        layout.addWidget(vol_label)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(50)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        layout.addWidget(self.volume_slider)

        # 全屏
        self.fullscreen_btn = QPushButton('⛶')
        self.fullscreen_btn.setStyleSheet(btn_style)
        self.fullscreen_btn.clicked.connect(self._toggle_fullscreen)
        layout.addWidget(self.fullscreen_btn)

        # 定时更新进度
        self._progress_timer = QTimer()
        self._progress_timer.setInterval(500)
        self._progress_timer.timeout.connect(self._update_progress)
        self._progress_timer.start()

        return bar

    # ----------------------------------------------------------
    #  播放器初始化
    # ----------------------------------------------------------

    def _setup_player(self):
        """初始化 mpv 播放器"""
        wid = int(self.player_container.winId())
        if self.media_player.init_player(wid):
            self.media_player.set_volume(50)
            self.media_player.set_on_end(self._on_play_end)
        else:
            self.statusBar().showMessage('⚠️ mpv 初始化失败，播放功能不可用', 10000)

    def _setup_statusbar(self):
        self.statusBar().showMessage('就绪')

    # ----------------------------------------------------------
    #  源管理
    # ----------------------------------------------------------

    def _refresh_source_dropdown(self):
        """刷新源下拉框"""
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        for src in self.state.sources:
            if src.enabled:
                self.source_combo.addItem(src.name, src)
        if self.state.last_source_index < self.source_combo.count():
            self.source_combo.setCurrentIndex(self.state.last_source_index)
        self.source_combo.blockSignals(False)

    def _on_source_selected(self, index: int):
        """源选择变化"""
        self.state.last_source_index = index
        self.state.save()

    def _load_current_source(self):
        """加载当前选中的源"""
        src = self.source_combo.currentData()
        if not src:
            self.home_status.setText('⚠️ 没有可用的源，请先添加订阅源')
            return

        self.home_status.setText(f'🔄 正在加载 {src.name}...')
        self._worker = WorkerThread(self.source_manager.fetch_source, src)
        self._worker.finished.connect(self._on_source_loaded)
        self._worker.error.connect(lambda e: self.home_status.setText(f'❌ 加载失败: {e}'))
        self._worker.start()

    def _on_source_loaded(self, result):
        """源加载完成"""
        categories = result.get('categories', [])
        live_channels = result.get('live_channels', [])

        # 更新首页
        self._show_categories(categories)

        # 更新直播
        if live_channels:
            self.live_page.set_channels(live_channels)

        self.statusBar().showMessage(f'✅ 加载完成: {len(categories)} 个分类, {len(live_channels)} 个直播频道')

    def _show_categories(self, categories: list):
        """在首页显示分类"""
        # 清空
        while self.home_grid.count():
            item = self.home_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not categories:
            self.home_status.setText('😔 该源没有分类数据')
            self.home_status.show()
            return

        self.home_status.hide()

        row = 0
        for cat in categories:
            # 分类标题
            title = QLabel(f'📂 {cat.name}')
            title.setStyleSheet("color: #aaa; font-size: 14px; font-weight: bold; margin-top: 8px;")
            self.home_grid.addWidget(title, row, 0, 1, 8)
            row += 1

            # 视频卡片
            cols = max(1, self.home_scroll.viewport().width() // 172)
            for i, video in enumerate(cat.items[:cols * 2]):  # 每分类最多显示2行
                card = VideoCard(video, self.cover_loader)
                src = self.source_combo.currentData()
                api_url = src.url if src else ''
                card.clicked.connect(partial(self._on_card_clicked, api_url))
                self.home_grid.addWidget(card, row + i // cols, i % cols)

            row += (len(cat.items[:cols * 2]) + cols - 1) // cols + 1

    def _on_card_clicked(self, api_url: str, video: VideoItem):
        """点击视频卡片"""
        self._load_detail(api_url, video.url)

    def _load_detail(self, api_url: str, vod_id: str):
        """加载视频详情"""
        self.statusBar().showMessage('🔄 加载详情...')
        self._worker = WorkerThread(self.source_manager.fetch_detail, api_url, vod_id)
        self._worker.finished.connect(self._show_detail)
        self._worker.error.connect(lambda e: self.statusBar().showMessage(f'❌ {e}'))
        self._worker.start()

    def _show_detail(self, video: VideoItem):
        """显示详情页"""
        if not video:
            self.statusBar().showMessage('❌ 未找到视频详情')
            return

        self.detail_page.set_video(video)
        self.detail_page.show()
        self.player_container.hide()

        # 添加到历史
        self.state.add_history(video)
        self._refresh_history()

        self.statusBar().showMessage(f'📺 {video.name}')

    def _hide_detail(self):
        """隐藏详情页"""
        self.detail_page.hide()
        self.player_container.show()

    # ----------------------------------------------------------
    #  播放控制
    # ----------------------------------------------------------

    def _play_url(self, url: str, title: str = ""):
        """播放指定 URL"""
        self.media_player.play(url, title)
        self.statusBar().showMessage(f'▶ 正在播放: {title}')
        self._hide_detail()

    def _play_episode(self, url: str, title: str, source_index: int):
        """播放剧集"""
        self._play_url(url, title)

    def _play_prev(self):
        """上一个"""
        if self.detail_page.video and self.detail_page.video.episodes:
            # 找到当前播放的 URL
            current_url = self.media_player.get_property('path') or ''
            episodes = self.detail_page.video.episodes
            for i, ep in enumerate(episodes):
                if ep['url'] in current_url or current_url in ep['url']:
                    if i > 0:
                        prev_ep = episodes[i - 1]
                        self._play_url(prev_ep['url'], f"{self.detail_page.video.name} - {prev_ep['name']}")
                    break

    def _play_next(self):
        """下一个"""
        if self.detail_page.video and self.detail_page.video.episodes:
            current_url = self.media_player.get_property('path') or ''
            episodes = self.detail_page.video.episodes
            for i, ep in enumerate(episodes):
                if ep['url'] in current_url or current_url in ep['url']:
                    if i < len(episodes) - 1:
                        next_ep = episodes[i + 1]
                        self._play_url(next_ep['url'], f"{self.detail_page.video.name} - {next_ep['name']}")
                    break

    def _toggle_pause(self):
        self.media_player.pause()

    def _stop_playback(self):
        self.media_player.stop()

    def _on_seek(self, pos):
        duration = self.media_player.duration
        if duration > 0:
            self.media_player.seek(pos / 1000 * duration)

    def _on_volume_changed(self, vol):
        self.media_player.set_volume(vol)

    def _toggle_fullscreen(self):
        self.media_player.toggle_fullscreen()

    def _on_play_end(self):
        """播放结束"""
        QTimer.singleShot(0, self._play_next)

    def _update_progress(self):
        """更新进度条和时间"""
        duration = self.media_player.duration
        time_pos = self.media_player.time_pos

        if duration > 0:
            self.progress_slider.blockSignals(True)
            self.progress_slider.setValue(int(time_pos / duration * 1000))
            self.progress_slider.blockSignals(False)

            # 更新时间标签
            def fmt(s):
                m, s = divmod(int(s), 60)
                h, m = divmod(m, 60)
                if h:
                    return f'{h:02d}:{m:02d}:{s:02d}'
                return f'{m:02d}:{s:02d}'

            self.time_label.setText(f'{fmt(time_pos)} / {fmt(duration)}')
        else:
            self.time_label.setText('00:00 / 00:00')

    # ----------------------------------------------------------
    #  封面图加载回调
    # ----------------------------------------------------------

    def _on_cover_loaded(self, url: str, pixmap: QPixmap):
        """封面图加载完成"""
        # 找到对应的 label（简单遍历）
        # 实际中 CoverLoader 信号已绑定到具体 label
        pass

    # ----------------------------------------------------------
    #  搜索
    # ----------------------------------------------------------

    def _do_search(self):
        """执行搜索"""
        keyword = self.search_input.text().strip()
        if not keyword:
            return

        src = self.source_combo.currentData()
        if not src:
            QMessageBox.warning(self, '提示', '请先选择一个订阅源')
            return

        self.left_tabs.setCurrentIndex(1)  # 切换到搜索页
        self.search_page.show_empty('🔄 搜索中...')

        self._worker = WorkerThread(self.source_manager.search, src.url, keyword)
        self._worker.finished.connect(lambda items: self.search_page.show_results(items, src.url))
        self._worker.error.connect(lambda e: self.search_page.show_empty(f'❌ 搜索失败: {e}'))
        self._worker.start()

    # ----------------------------------------------------------
    #  对话框
    # ----------------------------------------------------------

    def _open_source_dialog(self):
        dlg = SourceDialog(self.state, self)
        dlg.exec()
        self._refresh_source_dropdown()

    def _open_repo_dialog(self):
        dlg = RepoDialog(self.state, self)
        dlg.exec()
        self._refresh_source_dropdown()

    def _open_cloud_dialog(self):
        dlg = CloudDriveDialog(self.state, self)
        dlg.exec()
        self.cloud_page._refresh_drives()

    def _open_paste_link_dialog(self):
        """打开粘贴链接对话框"""
        dialog = PasteLinkDialog(parent=self, state=self.state)
        dialog.converted.connect(self._on_paste_link_converted)
        dialog.exec()

    def _on_paste_link_converted(self, repos, sources):
        """粘贴链接导入完成"""
        total = sum(len(r.sources) for r in repos) + len(sources)
        self.statusBar().showMessage(f'✅ 已导入 {total} 项', 5000)
        self._refresh_source_dropdown()

    def _open_url_dialog(self):
        """打开网络地址"""
        from PyQt6.QtWidgets import QInputDialog
        url, ok = QInputDialog.getText(self, '打开网络地址', '视频 URL:')
        if ok and url:
            self._play_url(url, '网络视频')

    def _open_local_file(self):
        """打开本地文件"""
        path, _ = QFileDialog.getOpenFileName(
            self, '打开视频文件', '',
            '视频文件 (*.mp4 *.mkv *.avi *.flv *.ts *.m3u8 *.rmvb *.wmv *.mov);;所有文件 (*)'
        )
        if path:
            self._play_url(path, os.path.basename(path))

    def _show_about(self):
        QMessageBox.about(
            self, '关于 TVBox Desktop',
            '<h3>TVBox Desktop</h3>'
            '<p>Windows 桌面版 TVBox 播放器</p>'
            '<p>技术栈: Python / PyQt6 / mpv</p>'
            '<p>版本: 1.0.0</p>'
        )

    # ----------------------------------------------------------
    #  收藏 / 历史
    # ----------------------------------------------------------

    def _refresh_favorites(self):
        """刷新收藏页"""
        while self._fav_grid.count():
            item = self._fav_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, video in enumerate(self.state.favorites):
            card = VideoCard(video, self.cover_loader)
            card.clicked.connect(partial(self._on_fav_clicked, video))
            self._fav_grid.addWidget(card, i // 5, i % 5)

    def _refresh_history(self):
        """刷新历史页"""
        while self._hist_grid.count():
            item = self._hist_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, video in enumerate(self.state.history[:20]):
            card = VideoCard(video, self.cover_loader)
            card.clicked.connect(partial(self._on_hist_clicked, video))
            self._hist_grid.addWidget(card, i // 5, i % 5)

    def _on_fav_clicked(self, video: VideoItem):
        src = self.source_combo.currentData()
        if src:
            self._load_detail(src.url, video.url)

    def _on_hist_clicked(self, video: VideoItem):
        src = self.source_combo.currentData()
        if src:
            self._load_detail(src.url, video.url)

    # ----------------------------------------------------------
    #  全局快捷键
    # ----------------------------------------------------------

    def keyPressEvent(self, event):
        # Ctrl+Shift+V: 粘贴链接导入
        if event.modifiers() == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            if event.key() == Qt.Key.Key_V:
                focused = QApplication.focusWidget()
                if not isinstance(focused, (QLineEdit, QTextEdit)):
                    self._open_paste_link_dialog()
                    return
        super().keyPressEvent(event)

    # ----------------------------------------------------------
    #  窗口事件
    # ----------------------------------------------------------

    def resizeEvent(self, event):
        """窗口大小变化时刷新卡片布局"""
        super().resizeEvent(event)
        # 可选: 刷新网格布局

    def closeEvent(self, event):
        """关闭窗口"""
        self.media_player.shutdown()
        self.state.save()
        self.cover_loader.terminate()
        event.accept()
