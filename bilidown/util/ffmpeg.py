"""ffmpeg 定位与一键下载。

探测优先级：
1. 用户在设置里手动指定的路径
2. 应用目录下已下载的 ffmpeg（漫游 AppData 的 bin 目录）
3. imageio-ffmpeg 捆绑的二进制
4. 系统 PATH

一键下载采用双源回退：优先 pip 安装 imageio-ffmpeg（体积小且免管理员），
失败再回退到下载官方静态包。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .paths import bin_dir

__all__ = ["FFmpegInfo", "find_ffmpeg", "probe_version", "download_ffmpeg", "FFMPEG_ZIP_URL"]

log = logging.getLogger(__name__)

#: 备用静态包下载地址
FFMPEG_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

#: Windows 下避免子进程弹出控制台窗口
CREATE_NO_WINDOW = 0x08000000

ProgressFn = Callable[[str, float], None]


@dataclass(slots=True)
class FFmpegInfo:
    """一个可用的 ffmpeg。"""

    path: Path
    source: str
    version: str = ""

    @property
    def exists(self) -> bool:
        return self.path.exists()


def _creation_flags() -> int:
    return CREATE_NO_WINDOW if sys.platform == "win32" else 0


def probe_version(path: Path) -> str:
    """读取 ffmpeg 版本号首行，失败时返回空串。"""
    if not path.exists():
        return ""
    try:
        result = subprocess.run(
            [str(path), "-version"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=_creation_flags(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("ffmpeg 版本探测失败：%s", exc)
        return ""
    first_line = (result.stdout or "").splitlines()
    return first_line[0].strip() if first_line else ""


def _from_bin_dir() -> Path | None:
    candidate = bin_dir() / "ffmpeg.exe"
    return candidate if candidate.exists() else None


def _from_imageio() -> Path | None:
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    try:
        exe = Path(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception as exc:  # 第三方库异常不应影响主流程
        log.debug("imageio-ffmpeg 定位失败：%s", exc)
        return None
    return exe if exe.exists() else None


def _from_path() -> Path | None:
    found = shutil.which("ffmpeg")
    return Path(found) if found else None


def find_ffmpeg(explicit: Path | None = None) -> FFmpegInfo | None:
    """按优先级查找可用的 ffmpeg，找不到返回 None。"""
    candidates: list[tuple[Path | None, str]] = [
        (explicit, "用户指定"),
        (_from_bin_dir(), "已下载"),
        (_from_imageio(), "内置"),
        (_from_path(), "系统 PATH"),
    ]
    for path, source in candidates:
        if path is not None and path.exists():
            return FFmpegInfo(path=path, source=source, version=probe_version(path))
    return None


async def _run_pip(*args: str) -> int:
    """在独立进程中执行 pip，返回退出码。"""
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "pip",
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            creationflags=_creation_flags(),
        )
    except OSError as exc:
        log.warning("无法启动 pip：%s", exc)
        return -1

    _, stderr = await process.communicate()
    if process.returncode:
        detail = (stderr or b"").decode("utf-8", errors="replace")
        log.warning("pip %s 失败：%s", " ".join(args), detail[:400])
    return process.returncode or 0


async def _install_via_pip(report: ProgressFn) -> Path | None:
    """方案一：pip 安装 imageio-ffmpeg 并复制到应用 bin 目录。"""
    report("正在通过 pip 安装 imageio-ffmpeg…", 0.05)
    if await _run_pip("install", "--upgrade", "imageio-ffmpeg") != 0:
        return None
    source = _from_imageio()
    if source is None:
        return None
    target = bin_dir() / "ffmpeg.exe"
    shutil.copy2(source, target)
    report("ffmpeg 已就绪", 1.0)
    return target


async def _download_zip(report: ProgressFn) -> Path | None:
    """方案二：下载官方静态包并解压出 ffmpeg.exe。"""
    import httpx

    target_dir = bin_dir()
    archive = target_dir / "ffmpeg-download.zip"
    report("正在下载 ffmpeg 静态包…", 0.0)

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=120.0) as client:
            async with client.stream("GET", FFMPEG_ZIP_URL) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length") or 0)
                done = 0
                with archive.open("wb") as handle:
                    async for chunk in response.aiter_bytes(1 << 20):
                        handle.write(chunk)
                        done += len(chunk)
                        if total:
                            report(f"正在下载 ffmpeg… {done * 100 // total}%", done / total * 0.9)
    except Exception as exc:
        log.warning("ffmpeg 静态包下载失败：%s", exc)
        archive.unlink(missing_ok=True)
        return None

    report("正在解压…", 0.92)
    extracted: Path | None = None
    try:
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                if name.replace("\\", "/").endswith("bin/ffmpeg.exe"):
                    destination = target_dir / "ffmpeg.exe"
                    with bundle.open(name) as src, destination.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    extracted = destination
                    break
    except (OSError, zipfile.BadZipFile) as exc:
        log.warning("ffmpeg 解压失败：%s", exc)
    finally:
        archive.unlink(missing_ok=True)

    if extracted is not None:
        report("ffmpeg 已就绪", 1.0)
    return extracted


async def download_ffmpeg(report: ProgressFn | None = None) -> FFmpegInfo:
    """一键获取 ffmpeg。

    优先 pip 方案；失败则回退静态包下载。
    两条路径都失败时抛出 RuntimeError，由调用方决定如何提示。
    """

    def _report(message: str, fraction: float) -> None:
        log.info("ffmpeg: %s", message)
        if report is not None:
            report(message, fraction)

    path = await _install_via_pip(_report)
    if path is None:
        _report("pip 方案不可用，改用直接下载…", 0.05)
        path = await _download_zip(_report)

    if path is None or not path.exists():
        raise RuntimeError("ffmpeg 获取失败：pip 与直接下载均不可用")

    return FFmpegInfo(path=path, source="已下载", version=probe_version(path))
