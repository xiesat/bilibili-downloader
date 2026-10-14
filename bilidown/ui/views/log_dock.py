"""可停靠的日志面板。"""

from __future__ import annotations

import logging

from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QDockWidget, QPlainTextEdit, QWidget

__all__ = ["LogDock"]

LEVEL_COLORS = {
    logging.DEBUG: "#9499A0",
    logging.INFO: "#61666D",
    logging.WARNING: "#E6A23C",
    logging.ERROR: "#F56C6C",
    logging.CRITICAL: "#F56C6C",
}


class LogDock(QDockWidget):
    """底部日志面板，最多保留 2000 行。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("日志", parent)
        self.setObjectName("LogDock")
        self.setAllowedAreas(
            self.allowedAreas()
        )

        self._view = QPlainTextEdit(self)
        self._view.setReadOnly(True)
        self._view.setMaximumBlockCount(2000)
        self._view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(9)
        self._view.setFont(font)

        self.setWidget(self._view)

    def append(self, message: str, level: int = logging.INFO) -> None:
        """追加一行带颜色的日志。"""
        cursor = self._view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor(LEVEL_COLORS.get(level, "#61666D")))
        cursor.insertText(message.rstrip() + "\n", fmt)

        self._view.setTextCursor(cursor)
        self._view.ensureCursorVisible()

    def clear(self) -> None:
        """清空日志。"""
        self._view.clear()
