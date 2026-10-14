"""asyncio 事件循环与 Qt 界面之间的桥。

界面必须在主线程访问控件，而网络与下载跑在后台线程的 asyncio 循环里。
Qt 的信号在跨线程发射时会自动排队到接收者所在线程，
因此这里用一个 QObject 承载全部对外信号，后台线程只管 emit，
界面侧只管 connect，天然避免了跨线程操作控件。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import Future
from typing import Any, Coroutine

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

__all__ = ["SignalBridge", "AsyncRunner"]


class SignalBridge(QObject):
    """后台线程 -> 主线程的全部事件出口。"""

    #: 单个任务状态或进度变化
    taskUpdated = Signal(object)
    #: 任务被移除
    taskRemoved = Signal()
    #: 一条日志（文本, 级别）
    logMessage = Signal(str, int)
    #: 全部任务结束
    allFinished = Signal(str)
    #: 登录状态变化（用户信息字典，未登录为空字典）
    loginStateChanged = Signal(object)
    #: 扫码状态变化（状态文本, 二维码 PNG 字节）
    qrStateChanged = Signal(str, object)
    #: ffmpeg 状态变化（FFmpegInfo 或 None）
    ffmpegStateChanged = Signal(object)
    #: 解析完成（条目列表, 错误信息列表）
    parseFinished = Signal(object, object)
    #: 一般性错误提示
    errorRaised = Signal(str)
    #: 信息提示
    infoRaised = Signal(str)


class AsyncRunner:
    """在后台线程里持有一个 asyncio 事件循环。"""

    def __init__(self, name: str = "bilidown-asyncio") -> None:
        self._name = name
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        """后台事件循环，尚未启动时为 None。"""
        return self._loop

    @property
    def running(self) -> bool:
        return self._loop is not None and self._thread is not None and self._thread.is_alive()

    def start(self, timeout: float = 5.0) -> None:
        """启动后台线程与事件循环。"""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._main, name=self._name, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError("后台事件循环启动超时")

    def _main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

    def submit(self, coro: Coroutine[Any, Any, Any]) -> Future[Any]:
        """把协程投递到后台循环，返回 concurrent.futures.Future。"""
        loop = self._loop
        if loop is None or not loop.is_running():
            coro.close()
            raise RuntimeError("后台事件循环未运行")
        return asyncio.run_coroutine_threadsafe(coro, loop)

    def submit_safe(self, coro: Coroutine[Any, Any, Any]) -> Future[Any] | None:
        """submit 的安全版本：失败时记录日志并返回 None。"""
        try:
            return self.submit(coro)
        except RuntimeError as exc:
            log.warning("任务投递失败：%s", exc)
            return None

    def stop(self, timeout: float = 5.0) -> None:
        """停止事件循环并等待线程退出。"""
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        self._loop = None
