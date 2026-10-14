"""图形界面：QApplication 装配与主窗口。

主窗口的详细布局在 ui/views 下的各个面板中实现，
本模块只负责把它们组装起来并接上事件桥。
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget

from .. import __version__
from ..util.paths import app_root

__all__ = ["run_gui", "MainWindow"]

log = logging.getLogger(__name__)


def _app_icon() -> QIcon:
    """优先使用打包资源里的图标，缺失时返回空图标。"""
    for candidate in (app_root() / "assets" / "app.ico", app_root() / "a.ico"):
        if candidate.exists():
            return QIcon(str(candidate))
    return QIcon()


def run_gui(argv: list[str] | None = None) -> int:
    """创建 QApplication 并进入事件循环。"""
    app = QApplication.instance() or QApplication(list(argv or sys.argv[:1]))
    app.setApplicationName("B站视频下载器")
    app.setApplicationDisplayName("B站视频下载器")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(_app_icon())

    window = MainWindow()
    window.show()
    return app.exec()


class MainWindow(QMainWindow):
    """主窗口。

    P1 阶段先搭好窗口骨架，界面内容在 P5 阶段完整实现。
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"B站视频下载器 v{__version__}")
        self.resize(1100, 760)
        self.setMinimumSize(880, 600)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("B站视频下载器", central)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: 600; color: #18191C;")

        subtitle = QLabel("P1 骨架已就绪：配置、模型、工具层与入口均可用", central)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("font-size: 13px; color: #9499A0;")

        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.setCentralWidget(central)
