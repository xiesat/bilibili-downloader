"""B 站 HTTP 客户端：统一请求头、Cookie、限速、重试退避与 WBI 签名。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time
import urllib.parse
from typing import Any

import httpx

from ..constants import API_ROOT, API_WEB, DEFAULT_USER_AGENT, REFERER
from ..errors import NetworkError, RiskControlError, api_error_from_code

__all__ = ["BiliClient"]

log = logging.getLogger(__name__)

#: 两次请求之间的最小间隔，避免触发风控
_MIN_INTERVAL = 0.1

#: 可重试的 HTTP 状态码
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

#: WBI 签名混淆表
_MIXIN_KEY_TAB = (
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
)


class BiliClient:
    """带重试与限速的异步 HTTP 客户端。

    典型用法::

        async with BiliClient(cookie=...) as client:
            payload = await client.get_json(API_WEB + "/view", params={"bvid": "BV1"})
    """

    def __init__(
        self,
        *,
        cookie: str = "",
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 30.0,
        max_retries: int = 3,
        max_connections: int = 64,
    ) -> None:
        self._cookie = cookie.strip()
        self._user_agent = user_agent
        self._timeout = float(timeout)
        self._max_retries = max(0, int(max_retries))
        self._max_connections = max(4, int(max_connections))
        self._client: httpx.AsyncClient | None = None
        self._throttle_lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._wbi_keys: tuple[str, str] | None = None
        self._wbi_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    async def __aenter__(self) -> BiliClient:
        return await self.start()

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def start(self) -> BiliClient:
        """建立连接池；重复调用是安全的。"""
        if self._client is not None:
            return self

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout, connect=min(15.0, self._timeout)),
            follow_redirects=True,
            headers=self._headers(),
            limits=httpx.Limits(
                max_connections=self._max_connections,
                max_keepalive_connections=self._max_connections // 2,
            ),
        )
        self._apply_cookies(self._cookie)
        await self._warmup()
        return self

    async def close(self) -> None:
        """关闭连接池。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def raw(self) -> httpx.AsyncClient:
        """底层 httpx 客户端，供下载引擎复用连接池。"""
        if self._client is None:
            raise NetworkError("客户端尚未启动，请先 await client.start()")
        return self._client

    # ------------------------------------------------------------------
    # Cookie
    # ------------------------------------------------------------------
    @property
    def cookie(self) -> str:
        """当前持有的完整 Cookie 字符串（含服务端下发的 buvid 等）。"""
        if self._client is None:
            return self._cookie
        parts: list[str] = []
        seen: set[str] = set()
        for item in self._client.cookies.jar:
            if item.name in seen:
                continue
            seen.add(item.name)
            parts.append(f"{item.name}={item.value}")
        return "; ".join(parts)

    def set_cookie(self, cookie: str) -> None:
        """替换当前 Cookie。"""
        self._cookie = (cookie or "").strip()
        if self._client is not None:
            self._apply_cookies(self._cookie)

    def cookie_value(self, name: str) -> str:
        """读取单个 Cookie 的值，不存在时返回空串。"""
        if self._client is None:
            for chunk in self._cookie.split(";"):
                key, _, value = chunk.strip().partition("=")
                if key == name:
                    return value
            return ""
        found = self._client.cookies.get(name)
        return found or ""

    def _apply_cookies(self, cookie: str) -> None:
        client = self._client
        if client is None:
            return
        client.cookies.clear()
        for chunk in cookie.split(";"):
            name, sep, value = chunk.strip().partition("=")
            if sep and name:
                client.cookies.set(name, value)

    # ------------------------------------------------------------------
    # 请求头
    # ------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self._user_agent,
            "Referer": REFERER,
            "Origin": "https://www.bilibili.com",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

    @property
    def media_headers(self) -> dict[str, str]:
        """下载 CDN 媒体流时使用的请求头。

        B 站 CDN 强校验 Referer，缺失会直接 403。
        """
        return {
            "User-Agent": self._user_agent,
            "Referer": REFERER,
            "Origin": "https://www.bilibili.com",
            "Accept": "*/*",
        }

    # ------------------------------------------------------------------
    # 预热：获取 buvid 指纹
    # ------------------------------------------------------------------
    async def _warmup(self) -> None:
        """获取 buvid3 / buvid4 指纹 Cookie，显著降低被风控概率。"""
        client = self._client
        if client is None:
            return
        if client.cookies.get("buvid3"):
            return
        try:
            response = await client.get(f"{API_ROOT}/frontend/finger/spi", timeout=10.0)
            if response.status_code != 200:
                log.warning("buvid 指纹接口返回 HTTP %s", response.status_code)
                return
            data = (response.json() or {}).get("data") or {}
        except Exception as exc:  # 预热失败不影响主流程
            log.warning("buvid 指纹获取失败，触发风控的概率会升高：%s", exc)
            return
        for name, key in (("buvid3", "b_3"), ("buvid4", "b_4")):
            value = data.get(key)
            if value:
                client.cookies.set(name, str(value), domain=".bilibili.com")
        log.info("buvid 指纹已就绪")


    # ------------------------------------------------------------------
    # 请求
    # ------------------------------------------------------------------
    async def _throttle(self) -> None:
        async with self._throttle_lock:
            now = time.monotonic()
            wait = _MIN_INTERVAL - (now - self._last_request_at)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """发起请求，自动限速并对可恢复错误做指数退避重试。"""
        await self.start()
        client = self.raw
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                await self._throttle()
                response = await client.request(method, url, **kwargs)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_error = exc
            else:
                if response.status_code == 412:
                    raise RiskControlError(
                        "请求被 B 站风控拦截（HTTP 412）",
                        detail="请稍后重试，或降低并发数",
                    )
                if response.status_code not in _RETRYABLE_STATUS:
                    return response
                last_error = NetworkError(f"服务端返回 HTTP {response.status_code}")

            if attempt < self._max_retries:
                delay = min(8.0, 0.6 * (2**attempt)) + random.uniform(0.0, 0.4)
                log.warning("请求失败（第 %d 次），%.1fs 后重试：%s", attempt + 1, delay, last_error)
                await asyncio.sleep(delay)

        raise NetworkError("网络请求失败", detail=str(last_error))

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        raise_on_code: bool = True,
    ) -> dict[str, Any]:
        """GET 并解析 JSON；raise_on_code 为真时把非 0 业务码转成异常。"""
        response = await self.request("GET", url, params=params, headers=headers)
        try:
            payload = response.json()
        except ValueError as exc:
            raise NetworkError("接口返回的不是合法 JSON", detail=response.text[:200]) from exc
        if not isinstance(payload, dict):
            raise NetworkError("接口返回结构异常", detail=str(payload)[:200])
        if raise_on_code:
            self.raise_for_code(payload)
        return payload

    async def post_json(
        self,
        url: str,
        *,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """POST 表单并解析 JSON。"""
        response = await self.request("POST", url, data=data, params=params, headers=headers)
        try:
            payload = response.json()
        except ValueError as exc:
            raise NetworkError("接口返回的不是合法 JSON", detail=response.text[:200]) from exc
        if not isinstance(payload, dict):
            raise NetworkError("接口返回结构异常", detail=str(payload)[:200])
        self.raise_for_code(payload)
        return payload

    @staticmethod
    def raise_for_code(payload: dict[str, Any]) -> None:
        """把接口业务错误码转成对应异常。"""
        code = payload.get("code")
        if code in (0, None):
            return
        raw = str(payload.get("message") or "")
        raise api_error_from_code(int(code), raw)

    # ------------------------------------------------------------------
    # WBI 签名
    # ------------------------------------------------------------------
    async def _ensure_wbi_keys(self) -> tuple[str, str]:
        if self._wbi_keys is not None:
            return self._wbi_keys
        async with self._wbi_lock:
            if self._wbi_keys is not None:
                return self._wbi_keys
            payload = await self.get_json(f"{API_WEB}/nav", raise_on_code=False)
            wbi = (payload.get("data") or {}).get("wbi_img") or {}
            img_key = str(wbi.get("img_url") or "").rsplit("/", 1)[-1].split(".")[0]
            sub_key = str(wbi.get("sub_url") or "").rsplit("/", 1)[-1].split(".")[0]
            if not img_key or not sub_key:
                raise NetworkError("无法获取 WBI 签名密钥")
            self._wbi_keys = (img_key, sub_key)
            return self._wbi_keys

    @staticmethod
    def _mixin_key(img_key: str, sub_key: str) -> str:
        raw = img_key + sub_key
        return "".join(raw[index] for index in _MIXIN_KEY_TAB)[:32]

    async def wbi_sign(self, params: dict[str, Any]) -> dict[str, Any]:
        """给请求参数追加 wts 与 w_rid，得到已签名的参数。"""
        img_key, sub_key = await self._ensure_wbi_keys()
        signed: dict[str, Any] = {k: v for k, v in params.items() if v is not None}
        signed["wts"] = int(time.time())
        query = urllib.parse.urlencode(sorted(signed.items()))
        filtered = "".join(ch for ch in query if ch not in "!'()*")
        digest = hashlib.md5((filtered + self._mixin_key(img_key, sub_key)).encode()).hexdigest()
        signed["w_rid"] = digest
        return signed
