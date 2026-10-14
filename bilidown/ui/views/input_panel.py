"""输入面板：批量粘贴视频地址。"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)

from .card import Card

__all__ = ["InputPanel"]

PLACEHOLDER = (
    "每行一个，支持以下形式（可混用，自动去重）：\n"
    "  BV 号        BV1GJ411x7h7\n"
    "  av 号        av170001\n"
    "  视频链接     https://www.bilibili.com/video/BV1GJ411x7h7/?p=2\n"
    "  分享短链     https://b23.tv/xxxxxxx\n"
    "  合集链接     https://space.bilibili.com/123/channel/collectiondetail?sid=456"
)


class InputPanel(Card):
    """地址输入区。只负责收集文本并发出意图，不做解析。"""

    parseRequested = Signal(str)
    clearRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("视频地址", parent)

        self._edit = QPlainTextEdit(self)
        self._edit.setPlaceholderText(PLACEHOLDER)
        self._edit.setMinimumHeight(68)
        # QPlainTextEdit 默认 sizeHint 接近 192px，若不封顶会把整张卡片撑得过高
        self._edit.setMaximumHeight(96)
        self._edit.setTabChangesFocus(True)

        self._parse_button = QPushButton("解析", self)
        self._parse_button.setObjectName("Primary")
        self._parse_button.setToolTip("解析输入并列出待下载的视频")
        self._parse_button.clicked.connect(self._emit_parse)

        self._paste_button = QPushButton("从剪贴板", self)
        self._paste_button.setToolTip("把剪贴板内容追加到输入框")
        self._paste_button.clicked.connect(self._paste)

        self._clear_button = QPushButton("清空", self)
        self._clear_button.clicked.connect(self._clear)

        hint = QLabel("支持批量输入，解析后可逐条勾选要下载的内容", self)
        hint.setObjectName("Hint")

        # 按钮与提示放在同一行，尽量压低上方区域的整体高度
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self._parse_button)
        buttons.addWidget(self._paste_button)
        buttons.addWidget(self._clear_button)
        buttons.addSpacing(12)
        buttons.addWidget(hint, 1)

        self.body.setSpacing(8)
        self.body.addWidget(self._edit, 1)
        self.body.addLayout(buttons)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def text(self) -> str:
        """当前输入内容。"""
        return self._edit.toPlainText()

    def set_text(self, value: str) -> None:
        """设置输入内容。"""
        self._edit.setPlainText(value)

    def append_text(self, value: str) -> None:
        """追加内容，自动补换行。"""
        current = self._edit.toPlainText()
        joined = f"{current.rstrip()}\n{value.strip()}\n" if current.strip() else f"{value.strip()}\n"
        self._edit.setPlainText(joined)
        self._edit.moveCursor(self._edit.textCursor().MoveOperation.End)

    def set_busy(self, busy: bool) -> None:
        """解析过程中禁用按钮，避免重复提交。"""
        self._parse_button.setEnabled(not busy)
        self._parse_button.setText("解析中…" if busy else "解析")

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _emit_parse(self) -> None:
        text = self._edit.toPlainText().strip()
        if not text:
            return
        self.parseRequested.emit(text)

    def _paste(self) -> None:
        clipboard = QApplication.clipboard()
        value = clipboard.text() if clipboard is not None else ""
        if value.strip():
            self.append_text(value)

    def _clear(self) -> None:
        self._edit.clear()
        self.clearRequested.emit()
