#!/usr/bin/env python3
"""TVBox Desktop — 入口文件"""

import sys
import os
import traceback
import warnings

# 切换到脚本所在目录
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 抑制 SSL 警告
warnings.filterwarnings('ignore', message='Unverified HTTPS request')


def main():
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        from PyQt6.QtCore import Qt, QCoreApplication
        from PyQt6.QtGui import QFont
    except ImportError as e:
        print(f"[致命错误] 缺少依赖: {e}")
        print("请运行: pip install -r requirements.txt")
        input("按回车键退出...")
        sys.exit(1)

    app = QApplication(sys.argv)

    # 设置全局异常处理，避免闪退
    def excepthook(exc_type, exc_value, exc_tb):
        err_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        print(f"[未捕获异常]\n{err_msg}")
        try:
            QMessageBox.critical(None, "TVBox Desktop — 错误",
                                 f"程序遇到未处理的异常:\n\n{err_msg}\n\n请截图反馈，谢谢！")
        except Exception:
            pass
    sys.excepthook = excepthook

    # 设置字体
    font = QFont("Microsoft YaHei", 10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)

    # 使用 Fusion 风格
    app.setStyle("Fusion")

    try:
        from ui.main_window import MainWindow
        window = MainWindow()
        window.show()
    except Exception as e:
        err_msg = traceback.format_exc()
        print(f"[启动失败]\n{err_msg}")
        QMessageBox.critical(None, "TVBox Desktop — 启动失败",
                             f"程序启动失败:\n\n{err_msg}\n\n请截图反馈，谢谢！")
        sys.exit(1)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
