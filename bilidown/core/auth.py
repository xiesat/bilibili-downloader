"""登录认证：扫码登录、Cookie 导入、登录态校验与静默续期。

为什么以扫码登录为主：
- 账号密码登录需要 RSA 加密 + appkey 签名，且 B 站已对 passport 开启极验风控
  （captcha 接口会下发 geetest 配置），异地/异设备登录必然触发滑块，
  实现成本与维护成本都远高于扫码。
- 扫码登录走官方授权通道，全程不接触账号密码，天然绕过极验，
  成功后服务端通过 Set-Cookie 下发 SESSDATA / bili_jct 等凭证。
"""

from __future__ import annotations

import base64
import io
import logging
import re
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..constants import API_PASSPORT, API_WEB
from ..errors import AuthRequiredError, BiliError, ConfigError, NetworkError
from .client import BiliClient
from .credentials import Credentials, clear_credentials, load_credentials, save_credentials

__all__ = ["AuthManager", "QrSession", "QrState", "normalize_cookie", "render_qr"]

log = logging.getLogger(__name__)

QR_GENERATE = f"{API_PASSPORT}/qrcode/generate"
QR_POLL = f"{API_PASSPORT}/qrcode/poll"
COOKIE_REFRESH = f"{API_PASSPORT}/cookie/refresh"
NAV = f"{API_WEB}/nav"

#: 二维码有效期约 180 秒
QR_TTL_SECONDS = 175


class QrState(StrEnum):
    """扫码登录的轮询状态。"""

    WAITING = "waiting"
    SCANNED = "scanned"
    EXPIRED = "expired"
    SUCCESS = "success"

    @property
    def label(self) -> str:
        return {
            QrState.WAITING: "等待扫码",
            QrState.SCANNED: "已扫码，请在手机上确认",
            QrState.EXPIRED: "二维码已失效，请刷新",
            QrState.SUCCESS: "登录成功",
        }[self]


#: B 站轮询返回的 code -> 状态
_POLL_STATES: dict[int, QrState] = {
    0: QrState.SUCCESS,
    86038: QrState.EXPIRED,
    86090: QrState.SCANNED,
    86101: QrState.WAITING,
}


@dataclass(slots=True)
class QrSession:
    """一次扫码登录会话。"""

    qrcode_key: str
    url: str
    image: bytes
    created_at: float

    @property
    def age(self) -> float:
        """已存在秒数。"""
        return time.time() - self.created_at

    @property
    def is_stale(self) -> bool:
        """是否即将失效，需要重新生成。"""
        return self.age > QR_TTL_SECONDS


def normalize_cookie(raw: str) -> str:
    """把用户粘贴的内容整理成标准的 Cookie 请求头。"""
    text = (raw or "").strip()
    if not text:
        return ""
    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1].strip()
    # 换行、制表符一律视为键值分隔符，兼容从 DevTools 多行粘贴的情形
    text = re.sub(r"[\r\n\t]+", ";", text)
    text = re.sub(r"\s*;\s*", "; ", text)
    text = re.sub(r"(?:;\s*)+", "; ", text)
    return text.strip(" ;")


def render_qr(url: str, *, box_size: int = 8, border: int = 2) -> bytes:
    """把登录链接渲染成 PNG 二维码字节。"""
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M

    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=box_size, border=border)
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="#18191C", back_color="#FFFFFF")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def data_uri(image: bytes) -> str:
    """把 PNG 字节转成 data URI，便于界面直接展示。"""
    return "data:image/png;base64," + base64.b64encode(image).decode("ascii")


def _extract_vip_label(data: dict[str, Any]) -> str:
    """nav 返回的 vip_label 在不同版本里可能是字符串或对象。"""
    label = data.get("vip_label")
    if isinstance(label, dict):
        return str(label.get("text") or "")
    if isinstance(label, str):
        return label
    return ""


class AuthManager:
    """登录态的唯一入口。

    与 BiliClient 共享同一个连接池，因此登录后获得的 Cookie
    会立刻对后续接口请求生效。
    """

    def __init__(self, client: BiliClient, *, persist: bool = True) -> None:
        self._client = client
        self._persist = persist
        self._creds = Credentials()
        self._user: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    @property
    def is_logged_in(self) -> bool:
        """当前是否处于已登录状态。"""
        return bool(self._user) and bool(self._creds.cookie)

    @property
    def cookie(self) -> str:
        """当前登录 Cookie。"""
        return self._creds.cookie

    @property
    def user(self) -> dict[str, Any]:
        """当前用户资料快照。"""
        return dict(self._user)

    @property
    def credentials(self) -> Credentials:
        """当前凭证对象。"""
        return self._creds

    @property
    def display_name(self) -> str:
        """界面展示用的用户名。"""
        return str(self._user.get("uname") or ("游客" if not self.is_logged_in else "已登录"))

    @property
    def vip_label(self) -> str:
        """大会员标识文本，非会员为空串。"""
        return str(self._user.get("vip_label") or "")

    @property
    def tier(self) -> str:
        """账号档位：guest / user / vip。"""
        if not self.is_logged_in:
            return "guest"
        return "vip" if self._user.get("is_vip") else "user"

    @property
    def tier_label(self) -> str:
        """账号档位的中文说明。"""
        return {"guest": "未登录", "user": "已登录", "vip": "大会员"}[self.tier]

    def set_persist(self, persist: bool) -> None:
        """设置是否把凭证加密落盘。"""
        self._persist = persist
        if not persist:
            clear_credentials()

    # ------------------------------------------------------------------
    # 登录
    # ------------------------------------------------------------------
    async def fetch_user(self) -> dict[str, Any]:
        """调用 nav 读取当前用户；未登录返回空字典。"""
        try:
            payload = await self._client.get_json(NAV, raise_on_code=False)
        except BiliError as exc:
            log.debug("nav 接口异常：%s", exc)
            return {}

        data = payload.get("data") or {}
        if payload.get("code") != 0 or not data.get("isLogin"):
            return {}

        return {
            "mid": int(data.get("mid") or 0),
            "uname": str(data.get("uname") or ""),
            "face": str(data.get("face") or ""),
            "is_vip": bool(data.get("vipStatus")),
            "vip_label": _extract_vip_label(data),
            "level": int((data.get("level_info") or {}).get("current_level") or 0),
        }

    async def load_saved(self) -> bool:
        """载入磁盘凭证并校验；失效则自动清除。"""
        creds = load_credentials()
        if creds.is_empty:
            return False

        self._client.set_cookie(creds.cookie)
        user = await self.fetch_user()
        if not user:
            log.info("已保存的登录凭证已失效，已清除")
            self._client.set_cookie("")
            self._creds = Credentials()
            clear_credentials()
            return False

        self._sync_credentials(creds, user)
        self._user = user
        await self.refresh()
        self._save()
        log.info("已恢复登录态：%s", user.get("uname"))
        return True

    async def create_qr_session(self) -> QrSession:
        """申请一个新的扫码登录二维码。"""
        payload = await self._client.get_json(QR_GENERATE)
        data = payload.get("data") or {}
        key = str(data.get("qrcode_key") or "")
        url = str(data.get("url") or "")
        if not key or not url:
            raise NetworkError("扫码登录二维码获取失败")
        return QrSession(
            qrcode_key=key,
            url=url,
            image=render_qr(url),
            created_at=time.time(),
        )

    async def poll_qr_session(self, session: QrSession) -> QrState:
        """轮询一次扫码状态；返回 SUCCESS 时登录已完成。"""
        response = await self._client.request("GET", QR_POLL, params={"qrcode_key": session.qrcode_key})
        try:
            payload = response.json()
        except ValueError as exc:
            raise NetworkError("扫码轮询返回异常") from exc

        data = payload.get("data") or {}
        code = int(data.get("code", -1))
        state = _POLL_STATES.get(code, QrState.WAITING)

        if state is QrState.SUCCESS:
            await self._finish_login(refresh_token=str(data.get("refresh_token") or ""))
        return state

    async def login_by_cookie(self, raw_cookie: str) -> dict[str, Any]:
        """用浏览器复制来的 Cookie 登录。"""
        cookie = normalize_cookie(raw_cookie)
        if not cookie:
            raise AuthRequiredError(-101, "Cookie 内容为空")

        self._client.set_cookie(cookie)
        user = await self.fetch_user()
        if not user:
            self._client.set_cookie("")
            raise AuthRequiredError(-101, "Cookie 无效或已过期，请重新复制")

        self._sync_credentials(Credentials(cookie=self._client.cookie), user)
        self._user = user
        self._save()
        log.info("Cookie 登录成功：%s", user.get("uname"))
        return self._user

    async def _finish_login(self, refresh_token: str = "") -> bool:
        """扫码确认后收尾：校验登录态并保存凭证。"""
        user = await self.fetch_user()
        if not user:
            raise AuthRequiredError(-101, "扫码已确认，但登录态校验失败，请重试")

        creds = Credentials(cookie=self._client.cookie, refresh_token=refresh_token)
        self._sync_credentials(creds, user)
        self._user = user
        self._save()
        log.info("扫码登录成功：%s（大会员：%s）", user.get("uname"), user.get("is_vip"))
        return True

    def _sync_credentials(self, creds: Credentials, user: dict[str, Any]) -> None:
        creds.cookie = self._client.cookie or creds.cookie
        creds.mid = int(user.get("mid") or 0)
        creds.uname = str(user.get("uname") or "")
        creds.avatar = str(user.get("face") or "")
        creds.is_vip = bool(user.get("is_vip"))
        creds.vip_label = str(user.get("vip_label") or "")
        creds.saved_at = time.time()
        self._creds = creds

    async def logout(self) -> None:
        """退出登录并清除本地凭证。"""
        self._client.set_cookie("")
        self._creds = Credentials()
        self._user = {}
        clear_credentials()
        log.info("已退出登录")

    async def refresh(self) -> bool:
        """尝试用 refresh_token 静默续期；失败仅返回 False。"""
        token = self._creds.refresh_token
        csrf = self._creds.csrf
        if not token or not csrf:
            return False
        try:
            payload = await self._client.post_json(
                COOKIE_REFRESH,
                data={"csrf": csrf, "refresh_token": token, "source": "main_web"},
            )
        except BiliError as exc:
            log.debug("凭证续期失败：%s", exc)
            return False

        new_token = str((payload.get("data") or {}).get("refresh_token") or "")
        if not new_token:
            return False

        self._creds.refresh_token = new_token
        self._creds.cookie = self._client.cookie
        self._creds.saved_at = time.time()
        self._save()
        log.debug("凭证已静默续期")
        return True

    async def ensure_fresh(self) -> bool:
        """下载前调用：登录态仍有效则返回 True。"""
        if not self._creds.cookie:
            return False
        user = await self.fetch_user()
        if user:
            self._user = user
            return True
        log.info("登录态已失效，转入游客模式继续")
        self._user = {}
        self._creds = Credentials()
        clear_credentials()
        return False

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _save(self) -> None:
        if not self._persist:
            return
        try:
            save_credentials(self._creds)
        except ConfigError as exc:
            log.warning("凭证保存失败：%s", exc)
