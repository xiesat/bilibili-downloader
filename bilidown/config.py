"""应用配置：默认值、取值范围校验、加载与保存。

配置文件位于漫游 AppData 下的 BiliDown/config.json。
注意：登录凭证不在这里，而是由 core.credentials 用 DPAPI 加密单独保存。
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .constants import DEFAULT_USER_AGENT
from .errors import ConfigError
from .util.paths import config_path, default_download_dir

__all__ = ["AppConfig", "load_config", "save_config", "VALID_MODES", "VALID_THEMES"]

log = logging.getLogger(__name__)

#: 支持的下载模式
VALID_MODES = ("auto", "dash", "progressive")
#: 支持的编码偏好
VALID_CODECS = ("avc1", "hev1", "av01")
#: 支持的界面主题
VALID_THEMES = ("light", "dark")

MIN_CONCURRENT, MAX_CONCURRENT = 1, 10
MIN_CHUNKS, MAX_CHUNKS = 1, 16
MIN_RETRIES, MAX_RETRIES = 0, 10


@dataclass
class AppConfig:
    """全部可配置项。每个字段都有合理默认值，配置文件缺失也能直接运行。"""

    # 存储
    download_dir: str = ""
    organize_by_season: bool = True
    keep_temp_files: bool = False

    # 画质与编码
    quality: int = 0  # 0 = 自动选择当前账号可用的最高画质
    codec_preference: str = "avc1"
    mode: str = "auto"  # auto / dash / progressive

    # 性能
    max_concurrent_videos: int = 3
    chunks_per_video: int = 8
    request_timeout: float = 30.0
    max_retries: int = 3

    # 外部程序
    ffmpeg_path: str = ""

    # 界面
    theme: str = "light"

    # 实验性后处理（默认关闭：必然损伤画质）
    delogo_enabled: bool = False
    delogo_region: str = ""

    # 网络身份
    user_agent: str = DEFAULT_USER_AGENT

    # ---- 运行期字段（不写入配置文件） ----
    #: 仅在内存中使用的 Cookie；持久化由 AuthManager 负责
    cookie: str = field(default="", repr=False, compare=False)
    #: 是否记住登录凭证
    remember_credentials: bool = True

    def __post_init__(self) -> None:
        if not self.download_dir:
            self.download_dir = str(default_download_dir())

    # ------------------------------------------------------------------
    # 派生属性
    # ------------------------------------------------------------------
    @property
    def download_path(self) -> Path:
        """下载目录的 Path 形式。"""
        return Path(self.download_dir).expanduser()

    @property
    def ffmpeg_path_or_none(self) -> Path | None:
        """用户显式指定的 ffmpeg 路径，未指定时为 None。"""
        return Path(self.ffmpeg_path).expanduser() if self.ffmpeg_path else None

    @property
    def is_logged_in(self) -> bool:
        """当前是否带有登录凭证。"""
        return bool(self.cookie)

    # ------------------------------------------------------------------
    # 校验与序列化
    # ------------------------------------------------------------------
    def normalize(self) -> AppConfig:
        """把越界或非法的取值收敛到合法区间，返回自身便于链式调用。"""
        if self.mode not in VALID_MODES:
            log.warning("非法的下载模式 %r，回退为 auto", self.mode)
            self.mode = "auto"
        if self.codec_preference not in VALID_CODECS:
            log.warning("非法的编码偏好 %r，回退为 avc1", self.codec_preference)
            self.codec_preference = "avc1"
        if self.theme not in VALID_THEMES:
            self.theme = "light"

        self.max_concurrent_videos = max(MIN_CONCURRENT, min(MAX_CONCURRENT, int(self.max_concurrent_videos)))
        self.chunks_per_video = max(MIN_CHUNKS, min(MAX_CHUNKS, int(self.chunks_per_video)))
        self.max_retries = max(MIN_RETRIES, min(MAX_RETRIES, int(self.max_retries)))
        self.request_timeout = max(5.0, min(300.0, float(self.request_timeout)))
        self.quality = max(0, int(self.quality))

        if not self.download_dir.strip():
            self.download_dir = str(default_download_dir())

        return self

    def to_dict(self) -> dict[str, object]:
        """转成可写入 JSON 的字典，排除运行期字段与凭证。"""
        data = asdict(self)
        data.pop("cookie", None)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> AppConfig:
        """从 JSON 字典构造，忽略未知字段。"""
        known = {f for f in cls.__dataclass_fields__ if f != "cookie"}
        kwargs = {k: v for k, v in data.items() if k in known}
        return cls(**kwargs)  # type: ignore[arg-type]


def load_config(path: Path | None = None) -> AppConfig:
    """读取配置；文件不存在或损坏时回退到默认值。"""
    target = path or config_path()
    if not target.exists():
        log.info("配置文件不存在，使用默认配置：%s", target)
        return AppConfig().normalize()

    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("配置文件读取失败（%s），使用默认配置", exc)
        return AppConfig().normalize()

    if not isinstance(raw, dict):
        log.warning("配置文件格式不是对象，使用默认配置")
        return AppConfig().normalize()

    try:
        return AppConfig.from_dict(raw).normalize()
    except (TypeError, ValueError) as exc:
        log.warning("配置文件字段类型异常（%s），使用默认配置", exc)
        return AppConfig().normalize()


def save_config(config: AppConfig, path: Path | None = None) -> None:
    """原子写入配置文件。"""
    target = path or config_path()
    payload = json.dumps(config.to_dict(), ensure_ascii=False, indent=2)
    tmp = target.with_suffix(".json.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(target)
    except OSError as exc:
        raise ConfigError("配置保存失败", detail=str(exc)) from exc
