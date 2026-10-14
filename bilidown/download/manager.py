"""任务调度：队列、并发、暂停 / 取消、断点续传与事件分发。

并发模型分两层：
- 视频级并发由 worker 协程数量决定（对应配置里的 max_concurrent_videos）
- 单视频内部再由分块并发决定（对应 chunks_per_video）

因此总连接数上限约为 两者之积，界面上会给出提示。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from ..config import AppConfig
from ..core.client import BiliClient
from ..core.metadata import MediaEntry
from ..core.playurl import build_plan
from ..errors import BiliError, CancelledError
from ..models import DownloadMode, DownloadTask, TaskState
from ..util.ffmpeg import FFmpegInfo, find_ffmpeg
from ..util.filename import sanitize
from ..util.paths import temp_dir
from .engine import ChunkedDownloader, DownloadControl
from .mux import merge_async

__all__ = ["DownloadManager", "ManagerEvent"]

log = logging.getLogger(__name__)

#: 同一任务进度事件的最小间隔（秒）
PROGRESS_INTERVAL = 0.12

#: 速度滑动窗口（秒）
SPEED_WINDOW = 0.35

#: 视为「占用中」的状态
BUSY_STATES = frozenset(
    {
        TaskState.PENDING,
        TaskState.QUEUED,
        TaskState.PARSING,
        TaskState.DOWNLOADING,
        TaskState.MUXING,
    }
)


@dataclass(slots=True)
class ManagerEvent:
    """管理器向外广播的事件。"""

    kind: str
    """task_added / task_updated / task_removed / log / finished"""

    task: DownloadTask | None = None
    message: str = ""


class DownloadManager:
    """下载任务管理器。

    运行在 asyncio 事件循环里；界面侧通过 submit / pause / resume / cancel
    这些同步方法投递意图，事件通过 on_event 回调抛出。
    """

    def __init__(
        self,
        config: AppConfig,
        *,
        on_event: Callable[[ManagerEvent], None] | None = None,
        client: BiliClient | None = None,
    ) -> None:
        self._config = config
        self._on_event = on_event
        self._client = client
        self._owns_client = client is None
        self._ffmpeg: FFmpegInfo | None = None

        self._tasks: dict[str, DownloadTask] = {}
        self._order: list[str] = []
        self._controls: dict[str, DownloadControl] = {}
        self._paused: set[str] = set()
        self._reserved: set[Path] = set()
        self._speed_state: dict[str, tuple[float, int]] = {}
        self._last_emit: dict[str, float] = {}

        self._pending: list[DownloadTask] = []
        self._wakeup = asyncio.Event()
        self._shutdown = asyncio.Event()
        self._workers: list[asyncio.Task] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    @property
    def tasks(self) -> list[DownloadTask]:
        """按加入顺序返回全部任务。"""
        return [self._tasks[key] for key in self._order if key in self._tasks]

    @property
    def ffmpeg(self) -> FFmpegInfo | None:
        """当前使用的 ffmpeg。"""
        return self._ffmpeg

    @property
    def client(self) -> BiliClient | None:
        """底层 HTTP 客户端。"""
        return self._client

    def stats(self) -> dict[str, int]:
        """各状态任务数统计。"""
        result = {"total": len(self._order), "completed": 0, "failed": 0, "active": 0, "waiting": 0}
        for task in self.tasks:
            if task.state is TaskState.COMPLETED:
                result["completed"] += 1
            elif task.state is TaskState.FAILED:
                result["failed"] += 1
            elif task.state.is_active:
                result["active"] += 1
            else:
                result["waiting"] += 1
        return result

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    async def start(self) -> None:
        """建立客户端、探测 ffmpeg 并启动 worker。"""
        self._config.normalize()
        self._loop = asyncio.get_running_loop()

        if self._client is None:
            self._client = BiliClient(
                cookie=self._config.cookie,
                user_agent=self._config.user_agent,
                timeout=self._config.request_timeout,
                max_retries=self._config.max_retries,
            )
        await self._client.start()

        self.reload_ffmpeg()

        self._shutdown.clear()
        count = max(1, self._config.max_concurrent_videos)
        self._workers = [
            asyncio.create_task(self._worker(index), name=f"bilidown-worker-{index}")
            for index in range(count)
        ]
        log.info(
            "调度器已启动：%d 个并发视频 × %d 个分块连接",
            count,
            self._config.chunks_per_video,
        )

    async def stop(self) -> None:
        """停止所有 worker 并释放资源。"""
        self._shutdown.set()
        self._wakeup.set()
        for worker in self._workers:
            worker.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

        if self._owns_client and self._client is not None:
            await self._client.close()
            self._client = None

    async def restart_workers(self) -> None:
        """在空闲时按最新配置重建 worker，用于并发数变更。"""
        if any(task.state.is_active for task in self.tasks):
            return
        for worker in self._workers:
            worker.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._shutdown.clear()
        count = max(1, self._config.max_concurrent_videos)
        self._workers = [
            asyncio.create_task(self._worker(index), name=f"bilidown-worker-{index}")
            for index in range(count)
        ]
        log.info("并发数已调整为 %d", count)

    def reload_ffmpeg(self) -> FFmpegInfo | None:
        """重新探测 ffmpeg（用户在一键下载后调用）。"""
        self._ffmpeg = find_ffmpeg(self._config.ffmpeg_path_or_none)
        if self._ffmpeg is not None:
            log.info("ffmpeg 已就绪：%s（来源：%s）", self._ffmpeg.path, self._ffmpeg.source)
        else:
            log.warning("未检测到 ffmpeg，DASH 高清模式不可用，将自动降级为渐进式")
        return self._ffmpeg

    async def wait_idle(self) -> None:
        """等到没有排队或进行中的任务（已暂停的任务不计入）。"""
        while self._pending or any(
            task.state in BUSY_STATES and task.task_id not in self._paused
            for task in self.tasks
        ):
            await asyncio.sleep(0.2)

    # ------------------------------------------------------------------
    # 任务增删
    # ------------------------------------------------------------------
    def add_entries(self, entries: Iterable[MediaEntry]) -> list[DownloadTask]:
        """把展开后的条目加入队列，返回新建的任务。"""
        created: list[DownloadTask] = []
        for entry in entries:
            task = DownloadTask(
                bvid=entry.video.bvid,
                cid=entry.page.cid,
                title=entry.video.title,
                part_title=entry.page.part,
                owner=entry.video.owner,
                cover=entry.video.cover,
                duration=entry.page.duration or entry.video.duration,
                season_title=entry.video.season_title,
                season_index=entry.video.season_index,
                page_index=entry.page.page,
                page_count=len(entry.video.pages),
                state=TaskState.QUEUED,
            )
            self._tasks[task.task_id] = task
            self._order.append(task.task_id)
            self._pending.append(task)
            created.append(task)
            self._emit(task, force=True)

        self._wake()
        return created

    def remove_task(self, task_id: str) -> None:
        """从列表里移除一个任务（进行中的会先被取消）。"""
        task = self._tasks.get(task_id)
        if task is None:
            return
        if task.state in BUSY_STATES:
            self.cancel(task_id)
        self._pending = [item for item in self._pending if item.task_id != task_id]
        self._tasks.pop(task_id, None)
        self._order = [key for key in self._order if key != task_id]
        self._paused.discard(task_id)
        self._reserved.discard(task.output_path) if task.output_path else None
        if self._on_event is not None:
            self._on_event(ManagerEvent(kind="task_removed", task=task))

    def clear_finished(self) -> None:
        """清除已完成 / 失败 / 已取消的任务。"""
        for task_id in [
            key
            for key in list(self._order)
            if self._tasks.get(key) is not None and self._tasks[key].state.is_terminal
        ]:
            task = self._tasks.pop(task_id, None)
            self._order.remove(task_id)
            self._last_emit.pop(task_id, None)
            self._speed_state.pop(task_id, None)
            if self._on_event is not None and task is not None:
                self._on_event(ManagerEvent(kind="task_removed", task=task))

    # ------------------------------------------------------------------
    # 控制
    # ------------------------------------------------------------------
    def pause(self, task_id: str) -> None:
        """暂停任务；排队中的任务会被移出待启动队列。"""
        task = self._tasks.get(task_id)
        if task is None or task.state.is_terminal:
            return

        control = self._controls.get(task_id)
        if control is not None:
            control.pause()
        else:
            self._paused.add(task_id)
        self._set_state(task, TaskState.PAUSED)

    def resume(self, task_id: str) -> None:
        """恢复任务。"""
        task = self._tasks.get(task_id)
        if task is None or task.state is TaskState.COMPLETED:
            return

        control = self._controls.get(task_id)
        if control is not None:
            control.resume()
            self._set_state(task, TaskState.DOWNLOADING)
            return

        if task_id in self._paused:
            self._paused.discard(task_id)
            task.state = TaskState.QUEUED
            self._pending.append(task)
            self._emit(task, force=True)
            self._wake()
        elif task.state in (TaskState.FAILED, TaskState.CANCELLED):
            self.retry(task_id)

    def cancel(self, task_id: str) -> None:
        """取消任务并清理临时文件。"""
        task = self._tasks.get(task_id)
        if task is None:
            return
        control = self._controls.get(task_id)
        if control is not None:
            control.cancel()
            return
        self._pending = [item for item in self._pending if item.task_id != task_id]
        self._paused.discard(task_id)
        self._cleanup_workdir(task)
        self._set_state(task, TaskState.CANCELLED)

    def retry(self, task_id: str) -> None:
        """重试失败或已取消的任务。"""
        task = self._tasks.get(task_id)
        if task is None:
            return
        self._cleanup_workdir(task)
        task.reset_progress()
        task.finished_at = 0.0
        task.state = TaskState.QUEUED
        self._paused.discard(task_id)
        if task not in self._pending:
            self._pending.append(task)
        self._emit(task, force=True)
        self._wake()

    # ------------------------------------------------------------------
    # worker
    # ------------------------------------------------------------------
    def _wake(self) -> None:
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._wakeup.set)
        else:
            self._wakeup.set()

    def _next_pending(self) -> DownloadTask | None:
        while self._pending:
            task = self._pending.pop(0)
            if task.task_id in self._paused:
                continue
            if task.state in (TaskState.PAUSED, TaskState.CANCELLED):
                continue
            return task
        return None

    async def _worker(self, index: int) -> None:
        log.debug("worker %d 已就绪", index)
        while not self._shutdown.is_set():
            try:
                await asyncio.wait_for(self._wakeup.wait(), timeout=1.0)
            except (asyncio.TimeoutError, TimeoutError):
                continue
            if self._shutdown.is_set():
                return

            while True:
                task = self._next_pending()
                if task is None:
                    break
                try:
                    await self._process(task)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.exception("任务 %s 处理异常", task.task_id)
                    self._fail(task, f"内部错误：{exc}")

            self._wakeup.clear()
            if self._pending:
                self._wakeup.set()
            self._maybe_finished()

    # ------------------------------------------------------------------
    # 单任务流程
    # ------------------------------------------------------------------
    async def _process(self, task: DownloadTask) -> None:
        assert self._client is not None, "调度器尚未启动"

        self._set_state(task, TaskState.PARSING)
        try:
            plan = await build_plan(
                self._client,
                bvid=task.bvid,
                cid=task.cid,
                quality=self._config.quality,
                codec=self._config.codec_preference,
                mode=DownloadMode(self._config.mode),
                ffmpeg_available=self._ffmpeg is not None,
            )
        except CancelledError:
            self._set_state(task, TaskState.CANCELLED)
            return
        except BiliError as exc:
            self._fail(task, str(exc))
            return

        task.plan = plan
        if plan.note:
            self._emit_log(f"{task.display_title}：{plan.note}")

        output = self._reserve_output(task)
        task.output_path = output

        control = DownloadControl()
        self._controls[task.task_id] = control
        self._speed_state[task.task_id] = (time.monotonic(), 0)
        self._set_state(task, TaskState.DOWNLOADING)

        work_dir = temp_dir() / task.task_id
        work_dir.mkdir(parents=True, exist_ok=True)

        def on_delta(delta: int) -> None:
            task.downloaded += delta
            self._tick(task)

        def on_total(total: int) -> None:
            task.total += total
            self._emit(task)

        downloader = ChunkedDownloader(
            chunks=self._config.chunks_per_video,
            timeout=self._config.request_timeout,
            retries=self._config.max_retries,
        )

        try:
            if plan.progressive is not None:
                result = await downloader.download(
                    self._client,
                    plan.progressive,
                    work_dir / "source.mp4",
                    control=control,
                    on_delta=on_delta,
                    on_total=on_total,
                )
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(result.path), str(output))
            else:
                video = await downloader.download(
                    self._client,
                    plan.video,
                    work_dir / "video.mp4",
                    control=control,
                    on_delta=on_delta,
                    on_total=on_total,
                )
                audio = None
                if plan.audio is not None:
                    audio = await downloader.download(
                        self._client,
                        plan.audio,
                        work_dir / "audio.mp4",
                        control=control,
                        on_delta=on_delta,
                        on_total=on_total,
                    )
                self._set_state(task, TaskState.MUXING)
                await merge_async(
                    video.path,
                    audio.path if audio else None,
                    output,
                    ffmpeg=self._ffmpeg,
                )
        except CancelledError:
            self._set_state(task, TaskState.CANCELLED)
            return
        except BiliError as exc:
            self._fail(task, str(exc))
            return
        except Exception as exc:
            log.exception("任务 %s 失败", task.task_id)
            self._fail(task, f"下载失败：{exc}")
            return
        finally:
            self._controls.pop(task.task_id, None)
            if not self._config.keep_temp_files:
                shutil.rmtree(work_dir, ignore_errors=True)

        task.downloaded = task.total or task.downloaded
        task.speed = 0.0
        task.finished_at = time.time()
        self._set_state(task, TaskState.COMPLETED)
        self._emit_log(f"已完成：{output.name}")

    def _reserve_output(self, task: DownloadTask) -> Path:
        """为任务预留一个不会与现有文件或其他任务冲突的输出路径。"""
        cfg = self._config
        base = cfg.download_path
        if cfg.organize_by_season and task.season_title:
            base = base / sanitize(task.season_title, max_length=60)
        base.mkdir(parents=True, exist_ok=True)

        stem = sanitize(task.title, max_length=90)
        if task.page_count > 1:
            stem = f"{stem} - P{task.page_index}"
            part = sanitize(task.part_title, max_length=40)
            if part and part != task.title:
                stem = f"{stem} {part}"
        stem = sanitize(stem, max_length=110)

        candidate = base / f"{stem}.mp4"
        index = 0
        while candidate.exists() or candidate in self._reserved:
            index += 1
            candidate = base / f"{stem} ({index}).mp4"
        self._reserved.add(candidate)
        return candidate

    def _cleanup_workdir(self, task: DownloadTask) -> None:
        shutil.rmtree(temp_dir() / task.task_id, ignore_errors=True)

    # ------------------------------------------------------------------
    # 状态与事件
    # ------------------------------------------------------------------
    def _set_state(self, task: DownloadTask, state: TaskState) -> None:
        task.state = state
        if state is TaskState.DOWNLOADING and not task.started_at:
            task.started_at = time.time()
        self._emit(task, force=True)

    def _fail(self, task: DownloadTask, message: str) -> None:
        task.error = message
        task.speed = 0.0
        task.finished_at = time.time()
        self._set_state(task, TaskState.FAILED)
        self._emit_log(f"失败：{task.display_title} —— {message}")

    def _tick(self, task: DownloadTask) -> None:
        """更新速度并节流上报进度。"""
        now = time.monotonic()
        last_time, last_bytes = self._speed_state.get(task.task_id, (now, task.downloaded))
        if now - last_time >= SPEED_WINDOW:
            instant = (task.downloaded - last_bytes) / (now - last_time)
            task.speed = instant if task.speed <= 0 else task.speed * 0.55 + instant * 0.45
            self._speed_state[task.task_id] = (now, task.downloaded)
        self._emit(task)

    def _emit(self, task: DownloadTask, *, force: bool = False) -> None:
        if self._on_event is None:
            return
        now = time.monotonic()
        if not force and now - self._last_emit.get(task.task_id, 0.0) < PROGRESS_INTERVAL:
            return
        self._last_emit[task.task_id] = now
        self._on_event(ManagerEvent(kind="task_updated", task=task))

    def _emit_log(self, message: str) -> None:
        log.info(message)
        if self._on_event is not None:
            self._on_event(ManagerEvent(kind="log", message=message))

    def _maybe_finished(self) -> None:
        if self._pending:
            return
        if any(task.state in BUSY_STATES for task in self.tasks):
            return
        if not self.tasks:
            return
        if self._on_event is not None:
            self._on_event(ManagerEvent(kind="finished", message="全部任务已结束"))
