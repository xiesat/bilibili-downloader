"""应用入口逻辑：GUI / CLI 分发。"""

from __future__ import annotations

import logging
import sys

from . import __version__

__all__ = ["main"]

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    """程序主入口。

    无参数时启动图形界面；带参数时走命令行模式。
    """
    from .util.logging import setup_logging

    args = list(sys.argv[1:] if argv is None else argv)

    # 打包版没有控制台，自检结果写入文件
    if args and args[0] == "--selftest":
        from pathlib import Path

        from .selftest import run_selftest

        target = Path(args[1]) if len(args) > 1 else Path.cwd() / "selftest.json"
        return run_selftest(target)

    setup_logging()
    log.info("B站视频下载器 v%s 启动，参数：%s", __version__, args or "(无，进入图形界面)")

    if args:
        from .cli import run_cli

        return run_cli(args)

    from .ui.app import run_gui

    return run_gui([])
