"""登录凭证的安全存储。

使用 Windows DPAPI（CryptProtectData / CryptUnprotectData）加密后落盘。
密文与当前 Windows 用户绑定——即使文件被复制到别的机器或别的账户也无法解密。
非 Windows 平台退化为明文并记录警告（本项目面向 Windows 桌面）。
"""

from __future__ import annotations

import base64
import ctypes
import json
import logging
import sys
import time
from ctypes import wintypes
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..errors import ConfigError
from ..util.paths import credentials_path

__all__ = [
    "Credentials",
    "dpapi_available",
    "load_credentials",
    "save_credentials",
    "clear_credentials",
]

log = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01
_FORMAT_VERSION = 1


class _DataBlob(ctypes.Structure):
    """对应 Win32 的 DATA_BLOB 结构。"""

    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def dpapi_available() -> bool:
    """当前平台是否支持 DPAPI 加密。"""
    if not _IS_WINDOWS:
        return False
    try:
        ctypes.WinDLL("crypt32.dll")
    except OSError:
        return False
    return True


def _blob_from_bytes(data: bytes) -> _DataBlob:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _bytes_from_blob(blob: _DataBlob) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def _dpapi(data: bytes, *, encrypt: bool) -> bytes:
    """调用 DPAPI 加密或解密。"""
    crypt32 = ctypes.WinDLL("crypt32.dll")
    kernel32 = ctypes.WinDLL("kernel32.dll")
    blob_in = _blob_from_bytes(data)
    blob_out = _DataBlob()

    if encrypt:
        ok = crypt32.CryptProtectData(
            ctypes.byref(blob_in),
            None,
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(blob_out),
        )
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(blob_in),
            None,
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(blob_out),
        )

    if not ok:
        raise OSError(f"DPAPI 调用失败，错误码 {ctypes.GetLastError()}")

    try:
        return _bytes_from_blob(blob_out)
    finally:
        kernel32.LocalFree(blob_out.pbData)


@dataclass
class Credentials:
    """一个账号的登录凭证与资料快照。"""

    cookie: str = ""
    refresh_token: str = ""
    mid: int = 0
    uname: str = ""
    avatar: str = ""
    is_vip: bool = False
    vip_label: str = ""
    saved_at: float = field(default_factory=time.time)

    @property
    def is_empty(self) -> bool:
        """是否没有可用凭证。"""
        return not self.cookie

    @property
    def csrf(self) -> str:
        """从 Cookie 中提取 bili_jct，用作 CSRF token。"""
        for chunk in self.cookie.split(";"):
            name, _, value = chunk.strip().partition("=")
            if name == "bili_jct":
                return value
        return ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Credentials:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})  # type: ignore[arg-type]


def _encode(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if dpapi_available():
        try:
            return base64.b64encode(_dpapi(raw, encrypt=True)).decode("ascii")
        except OSError as exc:
            log.warning("DPAPI 加密失败，退回明文存储：%s", exc)
    return base64.b64encode(raw).decode("ascii")


def _decode(blob_b64: str, *, encrypted: bool) -> dict[str, object]:
    raw = base64.b64decode(blob_b64.encode("ascii"))
    if encrypted:
        raw = _dpapi(raw, encrypt=False)
    data = json.loads(raw.decode("utf-8"))
    return data if isinstance(data, dict) else {}


def load_credentials(path: Path | None = None) -> Credentials:
    """读取并解密凭证；不存在或不可解密时返回空凭证。"""
    target = path or credentials_path()
    if not target.exists():
        return Credentials()
    try:
        envelope = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("凭证文件读取失败：%s", exc)
        return Credentials()

    if not isinstance(envelope, dict):
        return Credentials()

    try:
        payload = _decode(str(envelope.get("payload", "")), encrypted=bool(envelope.get("encrypted", True)))
    except (ValueError, OSError, UnicodeDecodeError) as exc:
        log.warning("凭证解密失败（可能换过 Windows 账户）：%s", exc)
        return Credentials()

    try:
        return Credentials.from_dict(payload)
    except (TypeError, ValueError) as exc:
        log.warning("凭证字段异常：%s", exc)
        return Credentials()


def save_credentials(creds: Credentials, path: Path | None = None) -> None:
    """加密并原子写入凭证。"""
    target = path or credentials_path()
    encrypted = dpapi_available()
    envelope = {
        "v": _FORMAT_VERSION,
        "encrypted": encrypted,
        "payload": _encode(creds.to_dict()),
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(target)
    except OSError as exc:
        raise ConfigError("凭证保存失败", detail=str(exc)) from exc


def clear_credentials(path: Path | None = None) -> None:
    """删除已保存的凭证。"""
    target = path or credentials_path()
    try:
        target.unlink(missing_ok=True)
    except OSError as exc:
        log.warning("凭证删除失败：%s", exc)
