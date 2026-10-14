"""音视频合并。

坚持使用 -c copy：只做封装，不做重编码，
这样既快又不会引入任何画质损失或转码水印。
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from pathlib import Path

from ..errors import MuxError
from ..util.ffmpeg import FFmpegInfo, find_ffmpeg

__all__ = ["merge", "merge_async", "apply_delogo", "CREATE_NO_WINDOW"]

log = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000


def _flags() -> int:
    return CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _run(command: list[str], *, timeout: float) -> None:
    """执行外部命令，失败时抛出 MuxError 并带上 stderr 尾部。"""
    log.debug("执行：%s", " ".join(command))
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_flags(),
        )
    except subprocess.TimeoutExpired as exc:
        raise MuxError("ffmpeg 执行超时", detail=f"{timeout:.0f}s") from exc
    except OSError as exc:
        raise MuxError("无法启动 ffmpeg", detail=str(exc)) from exc

    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-6:]
        raise MuxError("ffmpeg 处理失败", detail=" | ".join(tail))


def merge(
    video: Path,
    audio: Path | None,
    output: Path,
    *,
    ffmpeg: FFmpegInfo | None = None,
    timeout: float = 1800.0,
) -> Path:
    """把视频流与音频流合并成 mp4。

    audio 为 None 时只做封装（常见于无声视频）。
    """
    if not video.exists():
        raise MuxError("视频流文件不存在", detail=str(video))
    if audio is not None and not audio.exists():
        raise MuxError("音频流文件不存在", detail=str(audio))

    tool = ffmpeg or find_ffmpeg()
    if tool is None:
        raise MuxError("未找到可用的 ffmpeg，无法合并音视频")

    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(tool.path),
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", str(video),
    ]
    if audio is not None:
        command += ["-i", str(audio)]
        command += ["-map", "0:v:0", "-map", "1:a:0"]
    command += ["-c", "copy", "-movflags", "+faststart", str(output)]

    _run(command, timeout=timeout)
    if not output.exists() or output.stat().st_size == 0:
        raise MuxError("ffmpeg 未产出有效文件", detail=str(output))
    return output


async def merge_async(
    video: Path,
    audio: Path | None,
    output: Path,
    *,
    ffmpeg: FFmpegInfo | None = None,
    timeout: float = 1800.0,
) -> Path:
    """merge 的异步包装，避免阻塞事件循环。"""
    return await asyncio.to_thread(
        merge, video, audio, output, ffmpeg=ffmpeg, timeout=timeout
    )


def apply_delogo(
    source: Path,
    output: Path,
    region: str,
    *,
    ffmpeg: FFmpegInfo | None = None,
    timeout: float = 3600.0,
) -> Path:
    """实验性功能：用 delogo 滤镜抹掉画面内嵌水印。

    注意：这必须重编码视频，一定会损失画质，因此默认关闭。
    region 形如 x=10:y=10:w=120:h=40。
    """
    tool = ffmpeg or find_ffmpeg()
    if tool is None:
        raise MuxError("未找到可用的 ffmpeg")

    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(tool.path),
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", str(source),
        "-vf", f"delogo={region}",
        "-c:a", "copy",
        str(output),
    ]
    _run(command, timeout=timeout)
    return output
