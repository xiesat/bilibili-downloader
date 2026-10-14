"""运行期目录：配置、日志、缓存、ffmpeg 二进制。

程序目录可能位于系统保护目录（例如 D 盘的 Program Files），
因此所有运行期数据统一放在漫游 AppData 下的 BiliDown 目录。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = [
    "APP_DIR_NAME",
    "app_root",
    "resource_path",
    "app_data_dir",
    "config_path",
    "credentials_path",
    "logs_dir",
    "cache_dir",
    "bin_dir",
    "temp_dir",
    "default_download_dir",
]

APP_DIR_NAME = "BiliDown"


def app_root() -> Path:
    """项目根目录（源码运行与 PyInstaller 打包后都可用）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resource_path(relative: str) -> Path:
    """定位随程序分发的资源（图标等）。

    PyInstaller 打包后资源位于 sys._MEIPASS，源码运行时则位于项目根目录。
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidate = Path(base) / relative
        if candidate.exists():
            return candidate
    return app_root() / relative


def _roaming() -> Path:
    """Windows 漫游 AppData；其他平台回退到 XDG 风格目录。"""
    base = os.environ.get("APPDATA")
    if base:
        return Path(base)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg)
    return Path.home() / ".config"


def app_data_dir() -> Path:
    """漫游 AppData 下的 BiliDown 目录，不存在则创建。"""
    path = _roaming() / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ensure(sub: str) -> Path:
    path = app_data_dir() / sub
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    """配置文件路径。"""
    return app_data_dir() / "config.json"


def credentials_path() -> Path:
    """加密凭证文件路径。"""
    return app_data_dir() / "credentials.json"


def logs_dir() -> Path:
    """日志目录。"""
    return _ensure("logs")


def cache_dir() -> Path:
    """元数据缓存目录。"""
    return _ensure("cache")


def bin_dir() -> Path:
    """一键下载的 ffmpeg 存放目录。"""
    return _ensure("bin")


def temp_dir() -> Path:
    """下载临时分片目录。"""
    return _ensure("temp")


def default_download_dir() -> Path:
    """默认下载目录：用户视频库下的 BiliDown 子目录。"""
    home = Path.home()
    videos = home / "Videos"
    base = videos if videos.is_dir() else home
    return base / APP_DIR_NAME
