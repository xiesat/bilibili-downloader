"""账号面板：扫码登录、Cookie 导入与登录态展示。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .card import Card

__all__ = ["AccountPanel"]

#: 各档位对应的说明文案
TIER_HINTS = {
    "guest": "未登录 · 仅能下载 480P，登录后可解锁 1080P / 1080P+ / 4K",
    "user": "已登录 · 可下载 1080P",
    "vip": "大会员 · 可下载 1080P+ / 4K / 8K",
}


class AccountPanel(Card):
    """登录相关的全部交互。"""

    qrLoginRequested = Signal()
    cookieLoginRequested = Signal(str)
    logoutRequested = Signal()
    cancelQrRequested = Signal()

    PAGE_GUEST = 0
    PAGE_QR = 1
    PAGE_USER = 2

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("账号", parent)

        self.setMinimumWidth(300)
        self.setMaximumWidth(420)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._build_guest_page())
        self._stack.addWidget(self._build_qr_page())
        self._stack.addWidget(self._build_user_page())

        self.body.addWidget(self._stack)

        self.set_user({})

    # ------------------------------------------------------------------
    # 页面构造
    # ------------------------------------------------------------------
    def _build_guest_page(self) -> QWidget:
        page = QWidget(self)

        self._guest_hint = QLabel(TIER_HINTS["guest"], page)
        self._guest_hint.setObjectName("Hint")
        self._guest_hint.setWordWrap(True)

        qr_button = QPushButton("扫码登录", page)
        qr_button.setObjectName("Primary")
        qr_button.setToolTip("用手机 B 站 App 扫码，全程不接触账号密码")
        qr_button.clicked.connect(self.qrLoginRequested.emit)

        self._cookie_toggle = QPushButton("粘贴 Cookie", page)
        self._cookie_toggle.setToolTip("从浏览器开发者工具复制 Cookie 后粘贴")
        self._cookie_toggle.clicked.connect(self._toggle_cookie_row)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(qr_button)
        buttons.addWidget(self._cookie_toggle)
        buttons.addStretch(1)

        self._cookie_row = QWidget(page)
        self._cookie_edit = QLineEdit(self._cookie_row)
        self._cookie_edit.setPlaceholderText("粘贴形如 SESSDATA=xxx; bili_jct=yyy 的 Cookie")
        self._cookie_edit.returnPressed.connect(self._submit_cookie)
        submit = QPushButton("登录", self._cookie_row)
        submit.clicked.connect(self._submit_cookie)
        cookie_layout = QHBoxLayout(self._cookie_row)
        cookie_layout.setContentsMargins(0, 0, 0, 0)
        cookie_layout.setSpacing(8)
        cookie_layout.addWidget(self._cookie_edit, 1)
        cookie_layout.addWidget(submit)
        self._cookie_row.setVisible(False)

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._guest_hint)
        layout.addLayout(buttons)
        layout.addWidget(self._cookie_row)
        return page

    def _build_qr_page(self) -> QWidget:
        page = QWidget(self)

        self._qr_image = QLabel(page)
        self._qr_image.setFixedSize(132, 132)
        self._qr_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_image.setStyleSheet(
            "border: 1px solid #E3E5E7; border-radius: 10px; background: #FFFFFF;"
        )

        self._qr_status = QLabel("正在获取二维码…", page)
        self._qr_status.setObjectName("Hint")
        self._qr_status.setWordWrap(True)

        cancel = QPushButton("取消", page)
        cancel.clicked.connect(self.cancelQrRequested.emit)

        right = QVBoxLayout()
        right.setSpacing(8)
        right.addWidget(QLabel("请用手机 B 站 App 扫码登录", page))
        right.addWidget(self._qr_status)
        right.addWidget(cancel)
        right.addStretch(1)

        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(self._qr_image)
        layout.addLayout(right, 1)
        return page

    def _build_user_page(self) -> QWidget:
        page = QWidget(self)

        self._avatar = QLabel(page)
        self._avatar.setFixedSize(44, 44)
        self._avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar.setStyleSheet(
            "background: #FB7299; color: #FFFFFF; border-radius: 22px; font-size: 18px; font-weight: 600;"
        )

        self._name_label = QLabel(page)
        self._name_label.setObjectName("SectionTitle")
        self._tier_label = QLabel(page)
        self._tier_label.setObjectName("Hint")

        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(self._name_label)
        text.addWidget(self._tier_label)

        logout = QPushButton("退出登录", page)
        logout.clicked.connect(self.logoutRequested.emit)

        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._avatar)
        layout.addLayout(text, 1)
        layout.addWidget(logout)
        return page

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def set_user(self, user: dict) -> None:
        """根据用户信息切换页面。空字典表示未登录。"""
        if not user:
            self._stack.setCurrentIndex(self.PAGE_GUEST)
            self._cookie_row.setVisible(False)
            return

        name = str(user.get("uname") or "已登录")
        self._name_label.setText(name)
        self._avatar.setText(name[:1].upper())
        tier = "vip" if user.get("is_vip") else "user"
        self._tier_label.setText(TIER_HINTS[tier])
        # 会员标识文字较长，放进 tooltip 避免把窄栏撑破
        self._tier_label.setToolTip(str(user.get("vip_label") or ""))
        self._name_label.setToolTip(name)
        self._stack.setCurrentIndex(self.PAGE_USER)

    def show_qr(self, state_text: str, image: bytes | None = None) -> None:
        """切到扫码页并刷新二维码图片与状态。"""
        if image:
            pixmap = QPixmap()
            if pixmap.loadFromData(image, "PNG"):
                self._qr_image.setPixmap(
                    pixmap.scaled(
                        124,
                        124,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        self._qr_status.setText(state_text)
        self._stack.setCurrentIndex(self.PAGE_QR)

    def show_guest(self) -> None:
        """回到未登录页。"""
        self._stack.setCurrentIndex(self.PAGE_GUEST)

    def clear_cookie_input(self) -> None:
        """清空 Cookie 输入框。"""
        self._cookie_edit.clear()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _toggle_cookie_row(self) -> None:
        visible = not self._cookie_row.isVisible()
        self._cookie_row.setVisible(visible)
        self._cookie_toggle.setText("收起" if visible else "粘贴 Cookie")
        if visible:
            self._cookie_edit.setFocus()

    def _submit_cookie(self) -> None:
        value = self._cookie_edit.text().strip()
        if value:
            self.cookieLoginRequested.emit(value)
