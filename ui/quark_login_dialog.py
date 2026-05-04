#!/usr/bin/env python3
"""TVBox Desktop — 夸克网盘扫码登录对话框

展示二维码供用户扫描，轮询登录状态。
"""

import io
import qrcode
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QFrame, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage, QFont


class QRCheckWorker(QThread):
    """轮询二维码状态"""
    status_update = pyqtSignal(str, str)  # status, message
    login_success = pyqtSignal(str)  # nickname

    def __init__(self, client, session, parent=None):
        super().__init__(parent)
        self.client = client
        self.session = session
        self._running = True

    def run(self):
        import time
        attempts = 0
        max_attempts = 120  # 最多 2 分钟

        while self._running and attempts < max_attempts:
            time.sleep(1)
            attempts += 1

            session = self.client.check_qr_status(self.session)

            if session.status == "scanned":
                self.status_update.emit("scanned", "📱 已扫码，请在手机上确认登录")
            elif session.status == "confirmed":
                self.login_success.emit(self.client.get_nickname())
                return
            elif session.status == "expired":
                self.status_update.emit("expired", "⏰ 二维码已过期，请重新获取")
                return

        if self._running:
            self.status_update.emit("expired", "⏰ 等待超时，请重新获取二维码")

    def stop(self):
        self._running = False


class QuarkLoginDialog(QDialog):
    """夸克网盘扫码登录对话框"""

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self._session = None
        self._check_worker = None

        self.setWindowTitle("☁️ 夸克网盘登录")
        self.setFixedSize(420, 520)
        self.setStyleSheet("""
            QDialog {
                background: #0f0f1e;
                color: #eee;
            }
        """)

        self._setup_ui()
        self._request_qr()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(30, 30, 30, 30)

        # 标题
        title = QLabel("☁️ 夸克网盘授权登录")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # 说明
        desc = QLabel("使用夸克 APP 扫描二维码完成授权\n登录后可浏览和播放网盘内的视频")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet("color: #888; font-size: 13px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 二维码区域
        self.qr_frame = QFrame()
        self.qr_frame.setStyleSheet("""
            QFrame {
                background: white;
                border-radius: 12px;
                padding: 16px;
            }
        """)
        self.qr_frame.setFixedSize(260, 260)

        qr_layout = QVBoxLayout(self.qr_frame)
        qr_layout.setContentsMargins(16, 16, 16, 16)

        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setFixedSize(228, 228)
        self.qr_label.setText("⏳ 正在生成二维码...")
        self.qr_label.setStyleSheet("color: #333; font-size: 14px;")
        qr_layout.addWidget(self.qr_label)

        # 居中二维码
        qr_container = QHBoxLayout()
        qr_container.addStretch()
        qr_container.addWidget(self.qr_frame)
        qr_container.addStretch()
        layout.addLayout(qr_container)

        # 状态提示
        self.status_label = QLabel("⏳ 请打开夸克 APP 扫描二维码")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #aaa; font-size: 13px;")
        layout.addWidget(self.status_label)

        # 进度条
        self.progress = QProgressBar()
        self.progress.setMaximum(120)
        self.progress.setValue(120)
        self.progress.setMaximumHeight(3)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet("""
            QProgressBar { background: #1a1a36; border: none; border-radius: 1px; }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4a4aaa, stop:1 #7c7cff);
                border-radius: 1px;
            }
        """)
        layout.addWidget(self.progress)

        # 按钮区
        btn_layout = QHBoxLayout()

        self.refresh_btn = QPushButton("🔄 重新获取")
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background: #2a2a4e;
                border: 1px solid #3a3a6e;
                border-radius: 8px;
                color: #ccc;
                padding: 10px 20px;
                font-size: 13px;
            }
            QPushButton:hover { background: #3a3a5e; border-color: #5a5a8e; }
        """)
        self.refresh_btn.clicked.connect(self._request_qr)
        self.refresh_btn.hide()
        btn_layout.addWidget(self.refresh_btn)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: #2a2a4e;
                border: 1px solid #3a3a6e;
                border-radius: 8px;
                color: #ccc;
                padding: 10px 20px;
                font-size: 13px;
            }
            QPushButton:hover { background: #3a3a5e; border-color: #5a5a8e; }
        """)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        layout.addLayout(btn_layout)
        layout.addStretch()

    def _request_qr(self):
        """请求二维码"""
        self.refresh_btn.hide()
        self.status_label.setText("⏳ 正在生成二维码...")
        self.qr_label.setText("⏳ 正在生成二维码...")
        self.progress.setValue(120)

        # 停止旧的轮询
        if self._check_worker:
            self._check_worker.stop()

        # 请求二维码
        self._session = self.client.request_qrcode()

        if self._session.qrcode_url:
            self._show_qr_code(self._session.qrcode_url)
            self._start_polling()
        else:
            self.status_label.setText("❌ 获取二维码失败，请重试")
            self.refresh_btn.show()

    def _show_qr_code(self, url: str):
        """生成并显示二维码图片"""
        try:
            qr = qrcode.QRCode(version=1, box_size=8, border=2)
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")

            # 转为 QPixmap
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)

            qimg = QImage()
            qimg.loadFromData(buffer.read())
            pixmap = QPixmap.fromImage(qimg)
            pixmap = pixmap.scaled(220, 220, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            self.qr_label.setPixmap(pixmap)
        except ImportError:
            # qrcode 库未安装, 显示文本链接
            self.qr_label.setText(f"请访问:\n{url}\n\n(请安装 qrcode 库以显示二维码)\npip install qrcode[pil]")
            self.qr_label.setStyleSheet("color: #333; font-size: 11px;")

    def _start_polling(self):
        """开始轮询状态"""
        self._check_worker = QRCheckWorker(self.client, self._session)
        self._check_worker.status_update.connect(self._on_status_update)
        self._check_worker.login_success.connect(self._on_login_success)
        self._check_worker.start()

        # 进度倒计时
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick_progress)
        self._timer.start(1000)

    def _tick_progress(self):
        val = self.progress.value() - 1
        self.progress.setValue(max(0, val))
        if val <= 0:
            self._timer.stop()

    def _on_status_update(self, status: str, message: str):
        """状态更新"""
        self.status_label.setText(message)
        if status in ("expired", "error"):
            self._timer.stop()
            self.refresh_btn.show()

    def _on_login_success(self, nickname: str):
        """登录成功"""
        self._timer.stop()
        self.status_label.setText(f"✅ 登录成功！欢迎 {nickname}")
        self.status_label.setStyleSheet("color: #7cff7c; font-size: 13px;")

        # 延迟关闭
        QTimer.singleShot(1500, self.accept)

    def closeEvent(self, event):
        """关闭时停止轮询"""
        if self._check_worker:
            self._check_worker.stop()
        super().closeEvent(event)
