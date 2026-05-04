#!/usr/bin/env python3
"""TVBox Desktop — 海报墙首页组件

展示所有已订阅源的影视海报网格，支持:
  - 自动刮削元数据 (海报、评分、简介)
  - 分类筛选
  - 搜索
  - 点击进入详情
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea,
    QLabel, QLineEdit, QComboBox, QPushButton, QFrame, QSizePolicy,
    QProgressBar, QStackedWidget, QToolButton
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import QFont, QPixmap, QColor, QPainter, QBrush, QPen

from core.models import VideoItem, Category, SourceInfo, AppState
from core.source_manager import SourceManager
from core.scraper import MetadataScraper


# ============================================================
#  异步刮削线程
# ============================================================
class ScrapeWorker(QThread):
    """后台刮削元数据"""
    progress = pyqtSignal(int, int)  # current, total
    item_ready = pyqtSignal(VideoItem)  # 单个 item 刮削完成
    finished_all = pyqtSignal(list)  # 全部完成

    def __init__(self, items: list, scraper: MetadataScraper, parent=None):
        super().__init__(parent)
        self.items = items
        self.scraper = scraper

    def run(self):
        enriched = []
        total = len(self.items)
        for i, item in enumerate(self.items):
            result = self.scraper.enrich(item)
            enriched.append(result)
            self.item_ready.emit(result)
            self.progress.emit(i + 1, total)
            # 限速
            if i > 0 and i % 3 == 0:
                self.msleep(300)
        self.finished_all.emit(enriched)


# ============================================================
#  封面卡片 (升级版)
# ============================================================
class PosterCard(QFrame):
    """海报卡片组件"""
    clicked = pyqtSignal(VideoItem)

    def __init__(self, video: VideoItem, cover_loader, parent=None):
        super().__init__(parent)
        self.video = video
        self.cover_loader = cover_loader
        self._hovered = False

        self.setFixedSize(170, 280)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            PosterCard {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1a1a36, stop:1 #12122a);
                border: 1px solid #2a2a4e;
                border-radius: 12px;
            }
            PosterCard:hover {
                border-color: #7c7cff;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #252550, stop:1 #1a1a3a);
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 海报图
        self.cover_label = QLabel()
        self.cover_label.setFixedSize(154, 195)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setStyleSheet("""
            QLabel {
                background: #0a0a1a;
                border-radius: 8px;
                color: #444;
                font-size: 32px;
            }
        """)
        self.cover_label.setText('🎬')
        layout.addWidget(self.cover_label)

        # 标题
        title_label = QLabel(video.name)
        title_label.setStyleSheet("color: #eee; font-size: 13px; font-weight: bold;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        title_label.setWordWrap(True)
        title_label.setMaximumHeight(36)
        layout.addWidget(title_label)

        # 信息行: 年份 + 类型 + 评分
        info_parts = []
        if video.year:
            info_parts.append(video.year)
        if video.type_name:
            # 只取第一个类型
            type_short = video.type_name.split('/')[0].strip()
            if len(type_short) > 6:
                type_short = type_short[:6]
            info_parts.append(type_short)

        info_text = ' · '.join(info_parts)
        if info_text:
            info_label = QLabel(info_text)
            info_label.setStyleSheet("color: #888; font-size: 11px;")
            info_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
            layout.addWidget(info_label)

        layout.addStretch()

        # 异步加载封面
        if video.pic:
            self.cover_loader.enqueue(video.pic, self.cover_label)

    def update_cover(self, pixmap: QPixmap):
        """更新封面图"""
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                self.cover_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.cover_label.setPixmap(scaled)

    def enterEvent(self, event):
        self._hovered = True
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.video)
        super().mousePressEvent(event)


# ============================================================
#  海报墙主页
# ============================================================
class PosterWallPage(QWidget):
    """海报墙首页"""

    video_clicked = pyqtSignal(VideoItem)  # 点击视频卡片
    status_message = pyqtSignal(str)  # 状态栏消息

    def __init__(self, state: AppState, source_mgr: SourceManager,
                 scraper: MetadataScraper, cover_loader, parent=None):
        super().__init__(parent)
        self.state = state
        self.source_mgr = source_mgr
        self.scraper = scraper
        self.cover_loader = cover_loader

        self._all_items = []       # 所有视频条目
        self._current_category = "全部"
        self._scrape_worker = None

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # ---- 顶部: 搜索栏 + 分类筛选 ----
        top_bar = QHBoxLayout()
        top_bar.setSpacing(12)

        # 搜索框
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 搜索影视资源...")
        self.search_input.setMinimumHeight(40)
        self.search_input.setStyleSheet("""
            QLineEdit {
                background: #1a1a36;
                border: 1px solid #3a3a5e;
                border-radius: 20px;
                padding: 0 20px;
                color: #eee;
                font-size: 14px;
            }
            QLineEdit:focus {
                border-color: #6a6acc;
                background: #20204a;
            }
        """)
        self.search_input.returnPressed.connect(self._do_search)
        top_bar.addWidget(self.search_input, 3)

        # 分类下拉
        self.category_combo = QComboBox()
        self.category_combo.setMinimumHeight(40)
        self.category_combo.setStyleSheet("""
            QComboBox {
                background: #1a1a36;
                border: 1px solid #3a3a5e;
                border-radius: 8px;
                padding: 0 12px;
                color: #eee;
                font-size: 13px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #1a1a36;
                color: #eee;
                selection-background-color: #3a3a6e;
            }
        """)
        self.category_combo.currentTextChanged.connect(self._on_category_changed)
        top_bar.addWidget(self.category_combo, 1)

        # 刷新按钮
        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.setMinimumHeight(40)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4a4aaa, stop:1 #6a6acc);
                border: none;
                border-radius: 8px;
                color: white;
                font-size: 13px;
                font-weight: bold;
                padding: 0 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #5a5abb, stop:1 #7a7add);
            }
        """)
        refresh_btn.clicked.connect(self.refresh)
        top_bar.addWidget(refresh_btn)

        layout.addLayout(top_bar)

        # ---- 进度条 (刮削时显示) ----
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumHeight(3)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background: #1a1a36;
                border: none;
                border-radius: 1px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4a4aaa, stop:1 #7c7cff);
                border-radius: 1px;
            }
        """)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # ---- 提示横幅 ----
        self.banner_label = QLabel()
        self.banner_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.banner_label.setStyleSheet("""
            QLabel {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1a1a4a, stop:1 #2a2a5a);
                border: 1px solid #3a3a6e;
                border-radius: 10px;
                padding: 16px;
                color: #aaa;
                font-size: 14px;
            }
        """)
        self.banner_label.setText("📡 正在加载订阅源，请稍候...")
        layout.addWidget(self.banner_label)

        # ---- 海报网格 (可滚动) ----
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollBar:vertical {
                background: #1a1a2e;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #3a3a5e;
                border-radius: 4px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: #5a5a8e;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
        """)

        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(16)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self.scroll_area.setWidget(self.grid_container)
        layout.addWidget(self.scroll_area, 1)

    # ============================================================
    #  数据加载
    # ============================================================

    def refresh(self):
        """刷新海报墙"""
        self.banner_label.setText("📡 正在加载订阅源...")
        self.banner_label.show()
        self._clear_grid()

        # 在后台线程加载
        self._load_worker = WorkerThread(self._load_all_sources)
        self._load_worker.finished.connect(self._on_sources_loaded)
        self._load_worker.error.connect(lambda e: self.banner_label.setText(f"❌ 加载失败: {e}"))
        self._load_worker.start()

    def _load_all_sources(self):
        """加载所有订阅源 (在线程中执行)"""
        all_items = []
        categories = set()

        for source in self.state.sources:
            if not source.enabled:
                continue
            try:
                result = self.source_mgr.fetch_source(source)
                # fetch_source 返回 SourceResult 对象
                cats = result.categories if hasattr(result, 'categories') else result.get('categories', [])
                for cat in cats:
                    categories.add(cat.name)
                    for item in cat.items:
                        item.group = cat.name  # 保留分类信息
                        all_items.append(item)
                # 如果是多仓，也收集 urls 信息
                if hasattr(result, 'source_type') and result.source_type == 'multi':
                    # 多仓源本身不直接有视频，跳过
                    pass
            except Exception as e:
                print(f"[PosterWall] 加载源失败 [{source.name}]: {e}")

        return {'items': all_items, 'categories': list(categories)}

    def _on_sources_loaded(self, result):
        """源加载完成"""
        if isinstance(result, dict):
            self._all_items = result.get('items', [])
            categories = result.get('categories', [])
        else:
            self._all_items = getattr(result, 'items', [])
            categories = getattr(result, 'categories', [])

        if not self._all_items:
            self.banner_label.setText(
                "📭 暂无内容\n\n"
                "请点击右上角 🔄 刷新 或前往「仓库管理」添加订阅源"
            )
            self.banner_label.show()
            return

        self.banner_label.hide()

        # 更新分类下拉框
        self.category_combo.clear()
        self.category_combo.addItem("全部")
        self.category_combo.addItems(sorted(categories))

        # 显示海报网格
        self._display_items(self._all_items)

        # 启动后台刮削 (补充缺失元数据)
        self._start_scrape(self._all_items)

        self.status_message.emit(f"✅ 已加载 {len(self._all_items)} 个影视资源")

    def _display_items(self, items: list):
        """显示视频卡片网格"""
        self._clear_grid()

        # 计算每行数量
        width = self.scroll_area.viewport().width()
        cols = max(2, min(8, width // 190))

        for i, item in enumerate(items):
            if not isinstance(item, VideoItem):
                continue
            card = PosterCard(item, self.cover_loader)
            card.clicked.connect(self.video_clicked.emit)
            row = i // cols
            col = i % cols
            self.grid_layout.addWidget(card, row, col)

    def _clear_grid(self):
        """清空网格"""
        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    # ============================================================
    #  搜索 + 筛选
    # ============================================================

    def _do_search(self):
        """搜索"""
        keyword = self.search_input.text().strip()
        if not keyword:
            self._display_items(self._all_items)
            return

        # 本地搜索
        results = [
            item for item in self._all_items
            if keyword.lower() in item.name.lower()
            or keyword.lower() in (item.director or '').lower()
            or keyword.lower() in (item.actor or '').lower()
        ]

        if results:
            self._display_items(results)
            self.status_message.emit(f"🔍 搜索到 {len(results)} 个结果")
        else:
            self._clear_grid()
            self.banner_label.setText(f"🔍 未找到「{keyword}」相关内容")
            self.banner_label.show()

    def _on_category_changed(self, category: str):
        """分类切换"""
        self._current_category = category
        if category == "全部":
            self._display_items(self._all_items)
        else:
            filtered = [item for item in self._all_items if item.group == category]
            self._display_items(filtered)

    # ============================================================
    #  自动刮削
    # ============================================================

    def _start_scrape(self, items: list):
        """启动后台刮削"""
        # 只刮削缺少封面图或简介的条目
        need_scrape = [
            item for item in items
            if not item.pic or not item.description or not item.year
        ]

        if not need_scrape:
            return

        self.progress_bar.setMaximum(len(need_scrape))
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.status_message.emit(f"🔍 正在刮削 {len(need_scrape)} 个资源的元数据...")

        self._scrape_worker = ScrapeWorker(need_scrape, self.scraper)
        self._scrape_worker.progress.connect(self._on_scrape_progress)
        self._scrape_worker.item_ready.connect(self._on_scrape_item_ready)
        self._scrape_worker.finished_all.connect(self._on_scrape_done)
        self._scrape_worker.start()

    def _on_scrape_progress(self, current: int, total: int):
        self.progress_bar.setValue(current)

    def _on_scrape_item_ready(self, item: VideoItem):
        """单个条目刮削完成 — 更新对应卡片"""
        # 查找并更新对应的卡片
        for i in range(self.grid_layout.count()):
            widget = self.grid_layout.itemAt(i).widget()
            if isinstance(widget, PosterCard) and widget.video.name == item.name:
                widget.video = item
                if item.pic:
                    self.cover_loader.enqueue(item.pic, widget.cover_label)
                break

    def _on_scrape_done(self, enriched: list):
        """全部刮削完成"""
        self.progress_bar.hide()
        self.status_message.emit(f"✅ 元数据刮削完成，共处理 {len(enriched)} 个资源")


# 需要从 main_window 导入的 WorkerThread (保持一致)
class WorkerThread(QThread):
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
