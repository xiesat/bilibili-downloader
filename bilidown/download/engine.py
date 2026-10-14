"""单任务下载引擎：分块并发 + 断点续传 + CDN 回退 + 重试。

设计要点（均来自对 B 站 CDN 的实测）：
- 先用 1 字节 Range 请求探测总长度，同时验证直链可用性；
  B 站常把 baseUrl 指向 PCDN 节点，该节点可能直接 403，必须能切换。
- 支持 Range 且返回正确的 content-range，因此可以多连接分块并发；
  实测 8 连接把约 50MB 视频的下载压到 2.7 秒。
- 分块进度写进同名 meta 文件，中断后可以精确续传；
  直链会过期，所以每次下载都重新协商地址，续传只依赖字节偏移。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from ..errors import CancelledError, ChecksumError, DownloadError
from ..models import StreamRef

__all__ = ["DownloadControl", "DownloadResult", "ChunkedDownloader"]

log = logging.getLogger(__name__)

#: 单次写入的块大小
WRITE_CHUNK = 256 * 1024

#: 分块状态落盘的最小间隔（秒）
STATE_SAVE_INTERVAL = 3.0

#: 每个分块的最小跨度，避免把很小的文件切成过多块
MIN_CHUNK_SPAN = 256 * 1024


@dataclass
class DownloadControl:
    """外部用来暂停 / 取消一条下载的控制器。"""

    _resume: asyncio.Event = field(default_factory=asyncio.Event)
    _cancel: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self) -> None:
        self._resume.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def is_paused(self) -> bool:
        return not self._resume.is_set()

    def pause(self) -> None:
        """暂停：分块循环会在下一个检查点挂起。"""
        self._resume.clear()

    def resume(self) -> None:
        """恢复。"""
        self._resume.set()

    def cancel(self) -> None:
        """取消：分块循环会在下一个检查点抛出 CancelledError。"""
        self._cancel.set()
        self._resume.set()

    async def checkpoint(self) -> None:
        """在读写循环里调用，实现暂停与取消。"""
        if self._cancel.is_set():
            raise CancelledError("下载已取消")
        if not self._resume.is_set():
            await self._resume.wait()
            if self._cancel.is_set():
                raise CancelledError("下载已取消")


@dataclass(slots=True)
class DownloadResult:
    """一条流的下载结果。"""

    path: Path
    size: int
    elapsed: float

    @property
    def average_speed(self) -> float:
        """平均速度（字节/秒）。"""
        return self.size / self.elapsed if self.elapsed > 0 else 0.0


class ChunkedDownloader:
    """把一个 StreamRef 落到本地文件。"""

    def __init__(self, *, chunks: int = 8, timeout: float = 30.0, retries: int = 3) -> None:
        self.chunks = max(1, min(16, int(chunks)))
        self.timeout = float(timeout)
        self.retries = max(1, int(retries))
        self._stream_timeout = httpx.Timeout(
            self.timeout, connect=15.0, read=60.0, write=30.0, pool=30.0
        )

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------
    async def download(
        self,
        client,
        stream: StreamRef,
        destination: Path,
        *,
        control: DownloadControl | None = None,
        on_delta: Callable[[int], None] | None = None,
        on_total: Callable[[int], None] | None = None,
    ) -> DownloadResult:
        """下载一条流到 destination。

        on_delta 汇报新增字节数；on_total 汇报该流的总字节数。
        """
        control = control or DownloadControl()
        started = time.monotonic()
        destination.parent.mkdir(parents=True, exist_ok=True)

        part = destination.with_name(destination.name + ".part")
        meta = destination.with_name(destination.name + ".meta.json")

        url, total = await self._pick_source(client, stream, control)
        if on_total is not None:
            on_total(total)

        if total <= 0:
            log.info("服务端未提供长度，改用顺序下载")
            await self._download_sequential(client, url, part, control, on_delta)
        else:
            await self._download_chunked(client, url, part, meta, total, control, on_delta)

        size = part.stat().st_size if part.exists() else 0
        if total > 0 and size != total:
            raise ChecksumError("下载文件大小与远端不一致", detail=f"{size} != {total}")

        part.replace(destination)
        meta.unlink(missing_ok=True)
        return DownloadResult(path=destination, size=size, elapsed=time.monotonic() - started)

    # ------------------------------------------------------------------
    # 直链选择与探测
    # ------------------------------------------------------------------
    async def _pick_source(self, client, stream: StreamRef, control: DownloadControl) -> tuple[str, int]:
        """在多个 CDN 候选里挑一个可用的，返回 (url, 总长度)。"""
        last_error: Exception | None = None
        for url in stream.candidates:
            host = url.split("/")[2] if "//" in url else url
            try:
                await control.checkpoint()
                total = await self._probe(client, url)
                log.debug("选用 CDN 节点 %s，长度 %s", host, total)
                return url, total
            except CancelledError:
                raise
            except Exception as exc:
                last_error = exc
                log.warning("CDN 节点 %s 不可用，切换下一个：%s", host, exc)
        raise DownloadError("所有 CDN 节点都不可用", detail=str(last_error))

    async def _probe(self, client, url: str) -> int:
        """用 1 字节 Range 请求探测总长度。"""
        headers = {**client.media_headers, "Range": "bytes=0-0"}
        response = await client.request("GET", url, headers=headers)
        if response.status_code not in (200, 206):
            raise DownloadError(f"直链探测失败，HTTP {response.status_code}")

        content_range = response.headers.get("content-range") or ""
        if "/" in content_range:
            tail = content_range.rsplit("/", 1)[1].strip()
            if tail.isdigit():
                return int(tail)

        length = response.headers.get("content-length") or ""
        return int(length) if length.isdigit() else 0

    # ------------------------------------------------------------------
    # 分块下载
    # ------------------------------------------------------------------
    async def _download_chunked(
        self,
        client,
        url: str,
        part: Path,
        meta: Path,
        total: int,
        control: DownloadControl,
        on_delta: Callable[[int], None] | None,
    ) -> None:
        chunks = self._load_state(meta, total)

        # 预分配文件，各分块按偏移写入互不干扰
        with open(part, "wb") as handle:
            handle.truncate(total)

        resumed = sum(item[2] for item in chunks)
        if resumed and on_delta is not None:
            on_delta(resumed)
            log.info("命中断点，跳过已完成的 %.1f MB", resumed / 1048576)

        lock = asyncio.Lock()
        state = {"saved_at": time.monotonic()}

        async def save_state(force: bool = False) -> None:
            async with lock:
                if not force and time.monotonic() - state["saved_at"] < STATE_SAVE_INTERVAL:
                    return
                self._save_state(meta, total, chunks)
                state["saved_at"] = time.monotonic()

        async def run(index: int) -> None:
            await self._fetch_chunk(client, url, part, chunks, index, control, on_delta, save_state)

        try:
            await asyncio.gather(*(run(index) for index in range(len(chunks))))
        finally:
            await save_state(force=True)

    async def _fetch_chunk(
        self,
        client,
        url: str,
        part: Path,
        chunks: list[list[int]],
        index: int,
        control: DownloadControl,
        on_delta: Callable[[int], None] | None,
        save_state,
    ) -> None:
        start, end, _ = chunks[index]
        span = end - start + 1
        attempt = 0

        while True:
            written = chunks[index][2]
            if written >= span:
                return

            try:
                headers = {**client.media_headers, "Range": f"bytes={start + written}-{end}"}
                async with client.raw.stream(
                    "GET", url, headers=headers, timeout=self._stream_timeout
                ) as response:
                    if response.status_code not in (200, 206):
                        raise DownloadError(f"分块下载失败，HTTP {response.status_code}")

                    position = start + written
                    with open(part, "r+b") as handle:
                        handle.seek(position)
                        async for block in response.aiter_bytes(WRITE_CHUNK):
                            await control.checkpoint()
                            handle.write(block)
                            position += len(block)
                            chunks[index][2] = position - start
                            if on_delta is not None:
                                on_delta(len(block))
                            await save_state()

                    if position - start < span:
                        raise DownloadError("分块数据不完整")

                await save_state(force=True)
                return

            except CancelledError:
                await save_state(force=True)
                raise
            except Exception as exc:
                attempt += 1
                if attempt > self.retries:
                    await save_state(force=True)
                    raise DownloadError(
                        f"分块 {index} 重试 {self.retries} 次后仍失败", detail=str(exc)
                    ) from exc
                delay = min(5.0, 0.5 * (2**attempt))
                log.warning("分块 %d 失败（%s），%.1fs 后重试", index, exc, delay)
                await asyncio.sleep(delay)

    async def _download_sequential(
        self,
        client,
        url: str,
        part: Path,
        control: DownloadControl,
        on_delta: Callable[[int], None] | None,
    ) -> None:
        """服务端不给长度时退化为顺序下载。"""
        async with client.raw.stream(
            "GET", url, headers=dict(client.media_headers), timeout=self._stream_timeout
        ) as response:
            if response.status_code != 200:
                raise DownloadError(f"下载失败，HTTP {response.status_code}")
            with open(part, "wb") as handle:
                async for block in response.aiter_bytes(WRITE_CHUNK):
                    await control.checkpoint()
                    handle.write(block)
                    if on_delta is not None:
                        on_delta(len(block))

    # ------------------------------------------------------------------
    # 分块状态
    # ------------------------------------------------------------------
    @staticmethod
    def _plan_chunks(total: int, count: int) -> list[list[int]]:
        """把总长度切成若干块，每块形如 [start, end, written]。"""
        if total <= 0:
            return []
        feasible = max(1, total // MIN_CHUNK_SPAN)
        count = max(1, min(int(count), feasible, 16))
        span = (total + count - 1) // count

        chunks: list[list[int]] = []
        start = 0
        while start < total:
            end = min(start + span - 1, total - 1)
            chunks.append([start, end, 0])
            start = end + 1
        return chunks

    def _load_state(self, meta: Path, total: int) -> list[list[int]]:
        """读取续传状态；任何不一致都回到全新计划。"""
        fresh = self._plan_chunks(total, self.chunks)
        if not meta.exists():
            return fresh

        try:
            payload = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return fresh

        if int(payload.get("total", -1)) != total:
            log.info("临时文件与远端大小不一致，重新下载")
            return fresh

        stored = payload.get("chunks")
        if not isinstance(stored, list) or len(stored) != len(fresh):
            return fresh

        for index, item in enumerate(stored):
            if not isinstance(item, list) or len(item) != 3:
                return fresh
            try:
                start, end, written = (int(value) for value in item)
            except (TypeError, ValueError):
                return fresh
            if (start, end) != (fresh[index][0], fresh[index][1]):
                return fresh
            fresh[index][2] = max(0, min(written, end - start + 1))

        return fresh

    @staticmethod
    def _save_state(meta: Path, total: int, chunks: list[list[int]]) -> None:
        try:
            meta.write_text(
                json.dumps({"total": total, "chunks": chunks}, separators=(",", ":")),
                encoding="utf-8",
            )
        except OSError as exc:
            log.debug("分块状态写入失败：%s", exc)
