"""领域模型：视频元数据、流引用、下载任务与状态机。"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

__all__ = [
    "DownloadMode",
    "TaskState",
    "PageInfo",
    "VideoInfo",
    "StreamRef",
    "MediaPlan",
    "DownloadTask",
]


class DownloadMode(StrEnum):
    """下载模式。"""

    AUTO = "auto"
    """有 ffmpeg 时走 DASH，否则自动降级为渐进式。"""

    DASH = "dash"
    """音视频分离流，需要 ffmpeg 合并，画质最高。"""

    PROGRESSIVE = "progressive"
    """B 站已合流的单文件，免合并，但画质通常止步 720P。"""

    @property
    def label(self) -> str:
        return {"auto": "自动", "dash": "DASH 高清+合并", "progressive": "渐进式 MP4 免合并"}[self.value]


class TaskState(StrEnum):
    """下载任务状态。"""

    PENDING = "pending"
    PARSING = "parsing"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    MUXING = "muxing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        """是否为终态（不会再自动流转）。"""
        return self in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED)

    @property
    def is_active(self) -> bool:
        """是否正在消耗网络或 CPU。"""
        return self in (TaskState.DOWNLOADING, TaskState.MUXING, TaskState.PARSING)

    @property
    def label(self) -> str:
        return {
            TaskState.PENDING: "待处理",
            TaskState.PARSING: "解析中",
            TaskState.QUEUED: "排队中",
            TaskState.DOWNLOADING: "下载中",
            TaskState.PAUSED: "已暂停",
            TaskState.MUXING: "合并中",
            TaskState.COMPLETED: "已完成",
            TaskState.FAILED: "失败",
            TaskState.CANCELLED: "已取消",
        }[self]


@dataclass(slots=True)
class PageInfo:
    """视频的一个分 P。"""

    cid: int
    page: int
    part: str
    duration: int = 0


@dataclass(slots=True)
class VideoInfo:
    """一个稿件的元数据。"""

    bvid: str
    aid: int = 0
    title: str = ""
    owner: str = ""
    cover: str = ""
    duration: int = 0
    pages: list[PageInfo] = field(default_factory=list)
    season_title: str = ""
    season_index: int = 0

    @property
    def is_multi_part(self) -> bool:
        """是否为多 P 视频。"""
        return len(self.pages) > 1


@dataclass(slots=True)
class StreamRef:
    """一条可下载的媒体流（视频、音频或渐进式整文件）。"""

    url: str
    backup_urls: list[str] = field(default_factory=list)
    quality_id: int = 0
    quality_name: str = ""
    codecs: str = ""
    bandwidth: int = 0
    width: int = 0
    height: int = 0
    mime_type: str = ""
    size_hint: int = 0

    @property
    def candidates(self) -> list[str]:
        """主链接 + 备用链接，已去重并保持顺序。

        B 站常常把 baseUrl 指向 PCDN 节点，该节点可能 403，
        因此下载层必须准备回退到 backupUrl。
        """
        seen: set[str] = set()
        out: list[str] = []
        for url in (self.url, *self.backup_urls):
            if url and url not in seen:
                seen.add(url)
                out.append(url)
        return out

    @property
    def resolution(self) -> str:
        """形如 1920x1080 的分辨率文本。"""
        return f"{self.width}x{self.height}" if self.width and self.height else ""


@dataclass(slots=True)
class MediaPlan:
    """一个任务的完整下载方案。"""

    mode: DownloadMode = DownloadMode.AUTO
    quality_id: int = 0
    quality_name: str = ""
    video: StreamRef | None = None
    audio: StreamRef | None = None
    progressive: StreamRef | None = None
    requires_mux: bool = False
    note: str = ""

    @property
    def is_progressive(self) -> bool:
        """是否使用免合并的单文件模式。"""
        return self.progressive is not None and self.video is None


@dataclass
class DownloadTask:
    """一个可调度的下载任务（对应一个视频的一个分 P）。"""

    bvid: str
    cid: int
    title: str
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    part_title: str = ""
    owner: str = ""
    cover: str = ""
    duration: int = 0
    season_title: str = ""
    season_index: int = 0
    page_index: int = 1
    page_count: int = 1

    state: TaskState = TaskState.PENDING
    downloaded: int = 0
    total: int = 0
    speed: float = 0.0
    plan: MediaPlan | None = None
    output_path: Path | None = None
    error: str = ""

    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def progress(self) -> float:
        """下载进度，0.0 到 1.0。"""
        if self.total <= 0:
            return 0.0
        return min(1.0, self.downloaded / self.total)

    @property
    def eta(self) -> float | None:
        """预计剩余秒数；速度未知时返回 None。"""
        if self.speed <= 1 or self.total <= 0:
            return None
        remaining = max(0, self.total - self.downloaded)
        return remaining / self.speed if remaining else 0.0

    @property
    def display_title(self) -> str:
        """界面展示用的标题，多 P 时带上分 P 名。"""
        if self.part_title and self.part_title != self.title:
            return f"{self.title} - {self.part_title}"
        return self.title or self.bvid

    def reset_progress(self) -> None:
        """重试前清空进度。"""
        self.downloaded = 0
        self.total = 0
        self.speed = 0.0
        self.error = ""
