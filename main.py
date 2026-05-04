#!/usr/bin/env python3
"""TVBox Desktop — 入口文件"""

import sys
import os
import warnings

# 切换到脚本所在目录
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 抑制 SSL 警告
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QCoreApplication
from PyQt6.QtGui import QFont
from ui.main_window import MainWindow


def main():
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)

    # 设置字体
    font = QFont("Microsoft YaHei", 10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)

    # 使用 Fusion 风格
    app.setStyle("Fusion")

    # 创建并显示主窗口
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
