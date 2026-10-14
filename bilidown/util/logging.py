"""日志配置：滚动文件 + 可回调处理器（供界面日志面板使用）。"""

from __future__ import annotations

import logging
import logging.handlers
from collections.abc import Callable

from .paths import logs_dir

__all__ = ["setup_logging", "CallbackHandler", "get_logger"]

_LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class CallbackHandler(logging.Handler):
    """把日志记录转发给一个回调，用于界面的日志面板。

    回调在调用线程中执行，界面侧必须自行通过信号切回主线程。
    """

    def __init__(self, callback: Callable[[str, int], None], level: int = logging.INFO) -> None:
        super().__init__(level)
        self._callback = callback

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - 运行期行为
        try:
            self._callback(self.format(record), record.levelno)
        except Exception:
            # 日志处理绝不能拖垮业务逻辑
            self.handleError(record)


def setup_logging(level: int = logging.INFO, *, filename: str = "app.log") -> logging.Logger:
    """配置根日志：滚动文件 + 控制台。重复调用是安全的。"""
    root = logging.getLogger()
    if getattr(root, "_bilidown_configured", False):
        return root

    root.setLevel(level)
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    try:
        file_handler = logging.handlers.RotatingFileHandler(
            logs_dir() / filename,
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        root.addHandler(file_handler)
    except OSError:
        # 磁盘不可写时不应阻止程序启动
        pass

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(level)
    root.addHandler(console)

    root._bilidown_configured = True  # type: ignore[attr-defined]
    return root


def get_logger(name: str) -> logging.Logger:
    """获取一个模块级 logger。"""
    return logging.getLogger(name)
