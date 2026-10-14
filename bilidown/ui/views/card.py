"""卡片式容器。

不使用 QGroupBox：Qt 的样式表箱模型不会把 QGroupBox 的 padding / margin
计入 sizeHint，一旦样式里加了内边距，内容布局就会被压缩甚至互相重叠。
这里用 QFrame + 标题 QLabel 自己拼一个卡片，内外边距全部交给布局管理，
尺寸计算完全可预期。
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

__all__ = ["Card"]


class Card(QFrame):
    """带标题的卡片容器。子类往 self.body 里加内容即可。"""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFrameShape(QFrame.Shape.NoFrame)

        self._title = QLabel(title, self)
        self._title.setObjectName("CardTitle")

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(10)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 14)
        outer.setSpacing(10)
        outer.addWidget(self._title)
        outer.addLayout(self.body)

    def set_title(self, title: str) -> None:
        """更新卡片标题。"""
        self._title.setText(title)
