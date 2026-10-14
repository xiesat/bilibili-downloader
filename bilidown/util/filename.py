"""文件名处理：非法字符过滤、长度截断、重名去重、数值格式化。"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

__all__ = ["sanitize", "unique_path", "human_size", "human_speed", "format_duration"]

#: Windows 文件名非法字符与控制字符
_ILLEGAL = re.compile('[\\\\/:*?"<>|\r\n\t\x00-\x1f]')

#: Windows 保留设备名
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize(name: str, *, max_length: int = 120, fallback: str = "untitled") -> str:
    """把任意标题转成安全的文件名。

    - 把 Windows 非法字符替换为下划线
    - 折叠空白，去掉首尾的点和空格（Windows 不允许文件名以点或空格结尾）
    - 规避 CON / NUL 等保留设备名
    - 超长时截断并追加内容哈希，避免不同视频截断后互相撞名
    """
    text = _ILLEGAL.sub("_", name or "")
    text = re.sub(r"\s+", " ", text).strip(" .")

    if not text:
        return fallback

    if text.split(".")[0].upper() in _RESERVED:
        text = f"_{text}"

    if len(text) > max_length:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
        keep = max_length - len(digest) - 1
        text = f"{text[:keep].rstrip(' .')}_{digest}"

    return text or fallback


def unique_path(directory: Path, stem: str, suffix: str) -> Path:
    """在指定目录下找一个不冲突的路径，重名时追加 (1)、(2) 等后缀。"""
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    for index in range(1, 1000):
        candidate = directory / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    digest = hashlib.sha1(stem.encode("utf-8")).hexdigest()[:8]
    return directory / f"{stem}_{digest}{suffix}"


def human_size(num_bytes: float) -> str:
    """把字节数格式化成人类可读字符串。"""
    if num_bytes <= 0:
        return "—"
    size = float(num_bytes)
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def human_speed(bytes_per_second: float) -> str:
    """把速度格式化成类似 3.2 MB/s 的字符串。"""
    if bytes_per_second <= 0:
        return "—"
    return f"{human_size(bytes_per_second)}/s"


def format_duration(seconds: float) -> str:
    """把秒数格式化成 1:02:03 或 3:33。"""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
