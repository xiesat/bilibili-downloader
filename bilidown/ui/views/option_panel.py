"""下载选项面板：目录、画质、编码、并发与 ffmpeg 状态。

布局刻意压成三行，避免上方区域过高把标签页挤到没有空间。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from ...config import AppConfig
from ...constants import QUALITY_NAMES
from ...util.ffmpeg import FFmpegInfo
from .card import Card

__all__ = ["OptionPanel"]

#: 画质下拉项：0 表示自动
QUALITY_CHOICES: list[tuple[int, str]] = [(0, "自动（当前账号最高可用）")] + [
    (qn, name) for qn, name in sorted(QUALITY_NAMES.items(), reverse=True)
]

CODEC_CHOICES: list[tuple[str, str]] = [
    ("avc1", "H.264（兼容性最好）"),
    ("hev1", "H.265（更省体积）"),
    ("av01", "AV1（部分播放器不支持）"),
]

MODE_CHOICES: list[tuple[str, str]] = [
    ("auto", "自动"),
    ("dash", "DASH 高清 + 合并"),
    ("progressive", "渐进式 MP4（免合并）"),
]


class OptionPanel(Card):
    """下载参数设置。"""

    configChanged = Signal()
    browseRequested = Signal()
    downloadFFmpegRequested = Signal()
    pickFFmpegRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("下载选项", parent)

        # --- 第一行：目录 + 合集分文件夹 ---
        self._dir_edit = QLineEdit(self)
        self._dir_edit.setReadOnly(True)
        self._dir_edit.setPlaceholderText("选择保存目录")
        browse = QPushButton("浏览…", self)
        browse.clicked.connect(self.browseRequested.emit)

        self._season_check = QCheckBox("按合集建子文件夹", self)
        self._season_check.setChecked(True)
        self._season_check.stateChanged.connect(self._on_changed)

        row_dir = QHBoxLayout()
        row_dir.setSpacing(8)
        row_dir.addWidget(QLabel("保存到", self))
        row_dir.addWidget(self._dir_edit, 1)
        row_dir.addWidget(browse)
        row_dir.addSpacing(16)
        row_dir.addWidget(self._season_check)

        # --- 第二行：画质 / 编码 / 并发 / 分块 / 模式 ---
        self._quality_combo = QComboBox(self)
        for qn, name in QUALITY_CHOICES:
            self._quality_combo.addItem(name, qn)
        self._quality_combo.setMinimumWidth(150)

        self._codec_combo = QComboBox(self)
        for codec, name in CODEC_CHOICES:
            self._codec_combo.addItem(name, codec)
        self._codec_combo.setMinimumWidth(150)

        self._mode_combo = QComboBox(self)
        for mode, name in MODE_CHOICES:
            self._mode_combo.addItem(name, mode)
        self._mode_combo.setMinimumWidth(130)

        self._concurrent_spin = QSpinBox(self)
        self._concurrent_spin.setRange(1, 10)
        self._concurrent_spin.setToolTip("同时下载多少个视频")
        self._concurrent_spin.setFixedWidth(60)

        self._chunks_spin = QSpinBox(self)
        self._chunks_spin.setRange(1, 16)
        self._chunks_spin.setToolTip("单个视频分成多少个连接并行下载")
        self._chunks_spin.setFixedWidth(60)

        for combo in (self._quality_combo, self._codec_combo, self._mode_combo):
            combo.currentIndexChanged.connect(self._on_changed)
        for spin in (self._concurrent_spin, self._chunks_spin):
            spin.valueChanged.connect(self._on_changed)

        row_params = QHBoxLayout()
        row_params.setSpacing(8)
        row_params.addWidget(QLabel("画质", self))
        row_params.addWidget(self._quality_combo, 2)
        row_params.addWidget(QLabel("编码", self))
        row_params.addWidget(self._codec_combo, 2)
        row_params.addWidget(QLabel("并发", self))
        row_params.addWidget(self._concurrent_spin)
        row_params.addWidget(QLabel("分块", self))
        row_params.addWidget(self._chunks_spin)
        row_params.addWidget(QLabel("模式", self))
        row_params.addWidget(self._mode_combo, 2)

        # --- 第三行：ffmpeg ---
        self._ffmpeg_label = QLabel("检测中…", self)
        self._ffmpeg_label.setObjectName("Hint")
        self._ffmpeg_button = QPushButton("一键下载", self)
        self._ffmpeg_button.setToolTip("通过 pip 安装 imageio-ffmpeg，失败时回退到直接下载")
        self._ffmpeg_button.clicked.connect(self.downloadFFmpegRequested.emit)
        pick = QPushButton("手动指定…", self)
        pick.clicked.connect(self.pickFFmpegRequested.emit)

        row_ffmpeg = QHBoxLayout()
        row_ffmpeg.setSpacing(8)
        row_ffmpeg.addWidget(QLabel("ffmpeg", self))
        row_ffmpeg.addWidget(self._ffmpeg_label, 1)
        row_ffmpeg.addWidget(self._ffmpeg_button)
        row_ffmpeg.addWidget(pick)

        self.body.setSpacing(8)
        self.body.addLayout(row_dir)
        self.body.addLayout(row_params)
        self.body.addLayout(row_ffmpeg)

    # ------------------------------------------------------------------
    # 配置读写
    # ------------------------------------------------------------------
    def load_from(self, config: AppConfig) -> None:
        """把配置值填进控件（不触发 configChanged）。"""
        widgets = (
            self._quality_combo,
            self._codec_combo,
            self._mode_combo,
            self._concurrent_spin,
            self._chunks_spin,
            self._season_check,
        )
        for widget in widgets:
            widget.blockSignals(True)

        self._dir_edit.setText(config.download_dir)
        self._select_data(self._quality_combo, config.quality)
        self._select_data(self._codec_combo, config.codec_preference)
        self._select_data(self._mode_combo, config.mode)
        self._concurrent_spin.setValue(config.max_concurrent_videos)
        self._chunks_spin.setValue(config.chunks_per_video)
        self._season_check.setChecked(config.organize_by_season)

        for widget in widgets:
            widget.blockSignals(False)

    def apply_to(self, config: AppConfig) -> AppConfig:
        """把控件值写回配置并归一化。"""
        text = self._dir_edit.text().strip()
        if text:
            config.download_dir = text
        config.quality = int(self._quality_combo.currentData() or 0)
        config.codec_preference = str(self._codec_combo.currentData() or "avc1")
        config.mode = str(self._mode_combo.currentData() or "auto")
        config.max_concurrent_videos = self._concurrent_spin.value()
        config.chunks_per_video = self._chunks_spin.value()
        config.organize_by_season = self._season_check.isChecked()
        return config.normalize()

    # ------------------------------------------------------------------
    # 状态展示
    # ------------------------------------------------------------------
    def set_download_dir(self, path: str) -> None:
        self._dir_edit.setText(path)

    def set_ffmpeg(self, info: FFmpegInfo | None) -> None:
        """更新 ffmpeg 状态显示。"""
        if info is None:
            self._ffmpeg_label.setText("未检测到 · 将自动降级为渐进式（720P 免合并）")
            self._restyle("Warning")
            self._ffmpeg_button.setEnabled(True)
        else:
            version = info.version.split(" Copyright")[0].strip() if info.version else "已就绪"
            self._ffmpeg_label.setText(f"已就绪 · {info.source} · {version}")
            self._restyle("Success")
            self._ffmpeg_button.setEnabled(False)

    def set_ffmpeg_busy(self, busy: bool, message: str = "") -> None:
        """一键下载 ffmpeg 期间的按钮状态。"""
        self._ffmpeg_button.setEnabled(not busy)
        self._ffmpeg_button.setText("下载中…" if busy else "一键下载")
        if message:
            self._ffmpeg_label.setText(message)
            self._restyle("Hint")

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _restyle(self, object_name: str) -> None:
        """切换 objectName 后必须重新 polish，样式才会生效。"""
        self._ffmpeg_label.setObjectName(object_name)
        self._ffmpeg_label.style().unpolish(self._ffmpeg_label)
        self._ffmpeg_label.style().polish(self._ffmpeg_label)

    @staticmethod
    def _select_data(combo: QComboBox, value: object) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _on_changed(self, *_args: object) -> None:
        self.configChanged.emit()
