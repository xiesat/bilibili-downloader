"""应用入口逻辑：GUI / CLI 分发。"""

from __future__ import annotations

import logging
import os
import sys

from . import __version__

__all__ = ["main"]

log = logging.getLogger(__name__)


def _ensure_std_streams() -> None:
    """保证命令行模式有可用的标准输出。

    打包成窗口程序（console=False）后 sys.stdout / sys.stderr 都是 None，
    任何 print 都会抛 AttributeError，命令行模式会直接失败。
    这里先尝试附加到父进程控制台（从 cmd / PowerShell 启动时可用），
    失败则把输出重定向到日志文件，至少不会崩。
    """
    if sys.stdout is not None and sys.stderr is not None:
        return

    if sys.platform == "win32":
        try:
            import ctypes

            ATTACH_PARENT_PROCESS = 0xFFFFFFFF
            if ctypes.WinDLL("kernel32.dll").AttachConsole(ATTACH_PARENT_PROCESS):
                sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
                sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
                return
        except Exception:  # noqa: BLE001 - 附加控制台失败不应影响主流程
            pass

    try:
        from .util.paths import logs_dir

        stream = open(logs_dir() / "cli.log", "a", encoding="utf-8", buffering=1)
    except Exception:  # noqa: BLE001
        stream = open(os.devnull, "w", encoding="utf-8")

    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def main(argv: list[str] | None = None) -> int:
    """程序主入口。

    无参数时启动图形界面；带参数时走命令行模式。
    """
    from .util.logging import setup_logging

    args = list(sys.argv[1:] if argv is None else argv)
    _ensure_std_streams()

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
