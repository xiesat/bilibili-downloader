"""命令行模式：便于排错、批量与自动化。"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .config import VALID_CODECS, VALID_MODES, load_config
from .core.client import BiliClient
from .core.metadata import expand_ref
from .core.parser import parse_lines
from .download.manager import DownloadManager, ManagerEvent
from .errors import BiliError
from .models import TaskState
from .util.filename import human_size, human_speed

__all__ = ["run_cli", "build_parser"]

log = logging.getLogger(__name__)

_BLANK = " " * 120


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="bilidown",
        description="B站视频下载器（命令行模式）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("inputs", nargs="+", help="BV 号 / av 号 / 视频链接 / 合集链接")
    parser.add_argument("-o", "--output", help="下载目录")
    parser.add_argument("-q", "--quality", type=int, default=0, help="目标画质 qn，0 表示最高可用")
    parser.add_argument("--codec", default="avc1", choices=list(VALID_CODECS), help="视频编码偏好")
    parser.add_argument("-m", "--mode", default="auto", choices=list(VALID_MODES), help="下载模式")
    parser.add_argument("-j", "--jobs", type=int, default=3, help="同时下载的视频数")
    parser.add_argument("-c", "--chunks", type=int, default=8, help="单个视频的分块连接数")
    parser.add_argument("--season", action="store_true", help="稿件属于合集时展开整季")
    parser.add_argument("--cookie", default="", help="登录 Cookie，可提升可用画质")
    parser.add_argument("--ffmpeg", default="", help="指定 ffmpeg 可执行文件路径")
    return parser


async def _run(args: argparse.Namespace) -> int:
    config = load_config()
    if args.output:
        config.download_dir = args.output
    config.quality = args.quality
    config.codec_preference = args.codec
    config.mode = args.mode
    config.max_concurrent_videos = args.jobs
    config.chunks_per_video = args.chunks
    config.cookie = args.cookie
    if args.ffmpeg:
        config.ffmpeg_path = args.ffmpeg
    config.normalize()

    valid, invalid = parse_lines(" ".join(args.inputs))
    for ref in invalid:
        print(f"[跳过] 无法识别：{ref.raw}", file=sys.stderr)
    if not valid:
        print("没有可识别的输入", file=sys.stderr)
        return 2

    client = BiliClient(
        cookie=config.cookie,
        user_agent=config.user_agent,
        timeout=config.request_timeout,
        max_retries=config.max_retries,
    )
    await client.start()

    entries = []
    for ref in valid:
        try:
            entries.extend(
                await expand_ref(
                    client,
                    ref,
                    include_season=args.season,
                    notify=lambda message: print(f"[解析] {message}"),
                )
            )
        except BiliError as exc:
            print(f"[失败] {ref.display}：{exc}", file=sys.stderr)

    if not entries:
        await client.close()
        print("没有可下载的内容", file=sys.stderr)
        return 1

    print(f"共 {len(entries)} 个待下载视频，输出目录：{config.download_path}")
    if config.codec_preference != "avc1":
        print(f"编码偏好：{config.codec_preference}")

    #: 这些日志与下面的终态输出重复，命令行里不再单独打印
    redundant_prefixes = ("已完成：", "失败：")

    def on_event(event: ManagerEvent) -> None:
        task = event.task
        if event.kind == "log":
            if event.message.startswith(redundant_prefixes):
                return
            sys.stdout.write("\r" + _BLANK + "\r")
            print(f"[日志] {event.message}")
            return
        if event.kind != "task_updated" or task is None:
            return

        if task.state in (TaskState.DOWNLOADING, TaskState.MUXING) and task.total:
            line = (
                f"\r{task.state.label} {task.progress:6.1%} "
                f"{human_size(task.downloaded)}/{human_size(task.total)} "
                f"{human_speed(task.speed)}  {task.display_title[:36]}"
            )
            sys.stdout.write(line.ljust(120))
            sys.stdout.flush()
        elif task.state.is_terminal or task.state in (TaskState.PARSING, TaskState.QUEUED):
            sys.stdout.write("\r" + _BLANK + "\r")
            suffix = f"  <- {task.error}" if task.error else ""
            print(f"[{task.state.label}] {task.display_title[:60]}{suffix}")

    manager = DownloadManager(config, on_event=on_event, client=client)
    await manager.start()
    manager.add_entries(entries)
    await manager.wait_idle()
    stats = manager.stats()
    await manager.stop()

    print(f"完成 {stats['completed']} 个，失败 {stats['failed']} 个")
    return 0 if stats["failed"] == 0 else 1


def run_cli(argv: list[str]) -> int:
    """命令行入口。"""
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        return 130
