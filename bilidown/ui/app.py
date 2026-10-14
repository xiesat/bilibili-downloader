"""图形界面主窗口：把各视图、登录流程与下载调度器组装起来。

线程模型：
    主线程         Qt 界面，全部控件操作
    后台线程       asyncio 事件循环，网络、解析与下载
两者之间只通过 SignalBridge 的 Qt 信号通信，信号跨线程会自动排队，
因此界面侧永远不会被后台线程直接触碰。
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..config import AppConfig, load_config, save_config
from ..core.auth import AuthManager, QrState
from ..core.client import BiliClient
from ..core.metadata import MediaEntry, expand_ref
from ..core.parser import parse_lines
from ..download.manager import DownloadManager, ManagerEvent
from ..errors import BiliError
from ..models import DownloadTask, TaskState
from ..util.ffmpeg import FFmpegInfo, download_ffmpeg, find_ffmpeg
from ..util.logging import CallbackHandler
from ..util.paths import app_root
from .bridge import AsyncRunner, SignalBridge
from .theme import apply_theme
from .views.account_panel import AccountPanel
from .views.input_panel import InputPanel
from .views.log_dock import LogDock
from .views.option_panel import OptionPanel
from .views.result_tree import ResultTree
from .views.task_table import TaskTable

__all__ = ["run_gui", "MainWindow"]

log = logging.getLogger(__name__)

#: 配置自动保存延迟（毫秒）
CONFIG_SAVE_DELAY = 800


def _app_icon() -> QIcon:
    """优先使用打包资源里的图标。"""
    for candidate in (app_root() / "assets" / "app.ico", app_root() / "a.ico"):
        if candidate.exists():
            return QIcon(str(candidate))
    return QIcon()


def run_gui(argv: list[str] | None = None) -> int:
    """创建 QApplication 并进入事件循环。"""
    app = QApplication.instance() or QApplication(list(argv or sys.argv[:1]))
    app.setApplicationName("B站视频下载器")
    app.setApplicationDisplayName("B站视频下载器")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(_app_icon())

    window = MainWindow()
    window.show()
    return app.exec()


class MainWindow(QMainWindow):
    """主窗口。"""

    def __init__(self) -> None:
        super().__init__()

        self._config: AppConfig = load_config()
        self._client: BiliClient | None = None
        self._auth: AuthManager | None = None
        self._manager: DownloadManager | None = None

        self._bridge = SignalBridge()
        self._runner = AsyncRunner()
        self._bootstrapped = False
        self._parsing = False
        self._qr_cancelled = False

        self._entries: list[MediaEntry] = []
        self._task_states: dict[str, TaskState] = {}
        self._task_paths: dict[str, Path] = {}
        self._applied_concurrency = self._config.max_concurrent_videos

        self.setWindowTitle(f"B站视频下载器 v{__version__}")
        self.resize(1120, 840)
        self.setMinimumSize(940, 640)

        apply_theme(QApplication.instance(), self._config.theme)

        self._build_ui()
        self._connect_signals()
        self._install_log_handler()

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(CONFIG_SAVE_DELAY)
        self._save_timer.timeout.connect(self._persist_config)

        self._runner.start()
        self._runner.submit_safe(self._bootstrap())

    # ------------------------------------------------------------------
    # 构建界面
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget(self)
        central.setObjectName("CentralArea")

        self.input_panel = InputPanel(central)
        self.option_panel = OptionPanel(central)
        self.account_panel = AccountPanel(central)
        self.option_panel.load_from(self._config)

        top = QWidget(central)
        top.setObjectName("TopArea")
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        # 第一行左右分栏：左侧地址输入，右侧账号。
        # 纵向堆叠三张卡片会把标签页区域挤到没有空间，分栏后高度只取两者较大值。
        first_row = QHBoxLayout()
        first_row.setSpacing(8)
        first_row.addWidget(self.input_panel, 3)
        first_row.addWidget(self.account_panel, 2)

        top_layout.addLayout(first_row)
        top_layout.addWidget(self.option_panel)

        self.result_tree = ResultTree(central)
        self.result_tree.setMinimumHeight(120)
        self.task_table = TaskTable(central)
        self.task_table.setMinimumHeight(120)

        self.tabs = QTabWidget(central)
        self.tabs.addTab(self._build_result_tab(), "待下载")
        self.tabs.addTab(self._build_task_tab(), "下载队列")

        bottom = self._build_bottom_bar(central)

        # 上方按自身高度排布（stretch=0），标签页区域独占剩余空间（stretch=1）。
        # 不使用 QSplitter / QScrollArea：前者的最小高度约束会让面板互相重叠，
        # 后者的 sizeHint 不可靠，会把上方内容裁掉。
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 8)
        layout.setSpacing(10)
        layout.addWidget(top, 0)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(bottom, 0)
        self.setCentralWidget(central)

        self.log_dock = LogDock(self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.log_dock.hide()

        self._status_hint = QLabel("就绪", self)
        self._status_hint.setObjectName("Hint")
        self.statusBar().addWidget(self._status_hint, 1)
        self.statusBar().addPermanentWidget(QLabel(f"v{__version__}", self))

        self._refresh_stats()

    def _build_result_tab(self) -> QWidget:
        page = QWidget(self)
        select_all = QPushButton("全选", page)
        select_all.clicked.connect(lambda: self.result_tree.set_all_checked(True))
        select_none = QPushButton("全不选", page)
        select_none.clicked.connect(lambda: self.result_tree.set_all_checked(False))
        drop = QPushButton("移除勾选", page)
        drop.clicked.connect(self._on_drop_checked)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(select_all)
        row.addWidget(select_none)
        row.addWidget(drop)
        row.addStretch(1)

        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addLayout(row)
        layout.addWidget(self.result_tree, 1)
        return page

    def _build_task_tab(self) -> QWidget:
        page = QWidget(self)
        clear_button = QPushButton("清除已结束", page)
        clear_button.clicked.connect(self._on_clear_finished)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(clear_button)
        row.addStretch(1)

        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addLayout(row)
        layout.addWidget(self.task_table, 1)
        return page

    def _build_bottom_bar(self, parent: QWidget) -> QWidget:
        bar = QWidget(parent)
        bar.setObjectName("TopArea")

        self.start_button = QPushButton("开始下载", bar)
        self.start_button.setObjectName("Primary")
        self.start_button.clicked.connect(self._on_start)

        self.pause_button = QPushButton("暂停全部", bar)
        self.pause_button.clicked.connect(lambda: self._bulk("pause"))
        self.resume_button = QPushButton("恢复全部", bar)
        self.resume_button.clicked.connect(lambda: self._bulk("resume"))
        self.cancel_button = QPushButton("取消全部", bar)
        self.cancel_button.clicked.connect(lambda: self._bulk("cancel"))
        theme_button = QPushButton("切换主题", bar)
        theme_button.clicked.connect(self._on_toggle_theme)

        self.global_bar = QProgressBar(bar)
        self.global_bar.setRange(0, 1000)
        self.global_bar.setTextVisible(False)
        self.global_bar.setFixedWidth(220)
        self.global_bar.setFixedHeight(12)

        self.stats_label = QLabel("共 0 · 完成 0 · 失败 0", bar)
        self.stats_label.setObjectName("Hint")

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.start_button)
        layout.addWidget(self.pause_button)
        layout.addWidget(self.resume_button)
        layout.addWidget(self.cancel_button)
        layout.addStretch(1)
        layout.addWidget(self.global_bar)
        layout.addWidget(self.stats_label)
        layout.addWidget(theme_button)
        return bar

    # ------------------------------------------------------------------
    # 信号接线
    # ------------------------------------------------------------------
    def _connect_signals(self) -> None:
        self.input_panel.parseRequested.connect(self._on_parse)
        self.input_panel.clearRequested.connect(lambda: self.result_tree.clear_entries())

        self.option_panel.configChanged.connect(self._on_config_changed)
        self.option_panel.browseRequested.connect(self._on_browse)
        self.option_panel.downloadFFmpegRequested.connect(self._on_download_ffmpeg)
        self.option_panel.pickFFmpegRequested.connect(self._on_pick_ffmpeg)

        self.account_panel.qrLoginRequested.connect(self._on_qr_login)
        self.account_panel.cookieLoginRequested.connect(self._on_cookie_login)
        self.account_panel.logoutRequested.connect(self._on_logout)
        self.account_panel.cancelQrRequested.connect(self._on_cancel_qr)

        self.task_table.actionRequested.connect(self._on_task_action)

        self._bridge.taskUpdated.connect(self._on_task_updated)
        self._bridge.taskRemoved.connect(self._on_task_removed)
        self._bridge.logMessage.connect(self._on_log_message)
        self._bridge.allFinished.connect(self._on_all_finished)
        self._bridge.loginStateChanged.connect(self._on_login_state)
        self._bridge.qrStateChanged.connect(self._on_qr_state)
        self._bridge.ffmpegStateChanged.connect(self._on_ffmpeg_state)
        self._bridge.parseFinished.connect(self._on_parse_finished)
        self._bridge.errorRaised.connect(self._on_error)
        self._bridge.infoRaised.connect(self._on_info)

    def _install_log_handler(self) -> None:
        handler = CallbackHandler(
            lambda message, level: self._bridge.logMessage.emit(message, level)
        )
        handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
        handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(handler)

    # ------------------------------------------------------------------
    # 后台初始化
    # ------------------------------------------------------------------
    async def _bootstrap(self) -> None:
        try:
            self._client = BiliClient(
                user_agent=self._config.user_agent,
                timeout=self._config.request_timeout,
                max_retries=self._config.max_retries,
            )
            await self._client.start()
            self._auth = AuthManager(self._client, persist=self._config.remember_credentials)
            if self._config.remember_credentials:
                await self._auth.load_saved()
            self._bridge.loginStateChanged.emit(self._auth.user)
            self._bridge.ffmpegStateChanged.emit(find_ffmpeg(self._config.ffmpeg_path_or_none))
        except Exception as exc:  # noqa: BLE001 - 初始化失败也要让界面可用
            log.exception("初始化失败")
            self._bridge.errorRaised.emit(f"初始化失败：{exc}")
        finally:
            self._bootstrapped = True

    async def _ensure_ready(self) -> None:
        """等待后台初始化完成。"""
        while not self._bootstrapped:
            await asyncio.sleep(0.05)

    # ------------------------------------------------------------------
    # 解析
    # ------------------------------------------------------------------
    def _on_parse(self, text: str) -> None:
        if self._parsing:
            return
        self._parsing = True
        self.input_panel.set_busy(True)
        self._set_status("正在解析…")
        self._runner.submit_safe(self._parse(text))

    async def _parse(self, text: str) -> None:
        try:
            await self._ensure_ready()
            if self._client is None:
                self._bridge.parseFinished.emit([], ["网络客户端尚未就绪"])
                return

            valid, invalid = parse_lines(text)
            if not valid:
                errors = [f"{item.raw[:40]}：{item.error}" for item in invalid]
                self._bridge.parseFinished.emit([], errors or ["没有识别到有效的视频地址"])
                return

            errors = [f"{item.raw[:40]}：{item.error}" for item in invalid]
            entries: list[MediaEntry] = []
            for ref in valid:
                try:
                    entries.extend(await expand_ref(self._client, ref))
                except BiliError as exc:
                    errors.append(f"{ref.display}：{exc}")
            self._bridge.parseFinished.emit(entries, errors)
        except Exception as exc:  # noqa: BLE001
            log.exception("解析失败")
            self._bridge.parseFinished.emit([], [f"解析失败：{exc}"])

    def _on_parse_finished(self, entries: list[MediaEntry], errors: list[str]) -> None:
        self._parsing = False
        self.input_panel.set_busy(False)

        for message in errors:
            self._append_log(f"跳过：{message}", logging.WARNING)

        if entries:
            self._entries = list(entries)
            self.result_tree.set_entries(self._entries)
            self.tabs.setCurrentIndex(0)
            self.tabs.setTabText(0, f"待下载 ({len(entries)})")
            self._set_status(f"已解析 {len(entries)} 个视频，勾选后点击开始下载")
            self.log_dock.show()
        else:
            self.tabs.setTabText(0, "待下载")
            self._set_status("没有解析到可下载的内容")

    # ------------------------------------------------------------------
    # 下载
    # ------------------------------------------------------------------
    def _on_start(self) -> None:
        entries = self.result_tree.checked_entries()
        if not entries:
            self._show_warning("请先解析视频并勾选要下载的内容")
            return
        self.option_panel.apply_to(self._config)
        self._runner.submit_safe(self._start_download(entries))

    async def _start_download(self, entries: list[MediaEntry]) -> None:
        try:
            await self._ensure_ready()
            manager = await self._ensure_manager()
            manager.add_entries(entries)
            self._bridge.infoRaised.emit(f"已加入下载队列：{len(entries)} 个视频")
        except Exception as exc:  # noqa: BLE001
            log.exception("启动下载失败")
            self._bridge.errorRaised.emit(f"启动下载失败：{exc}")

    async def _ensure_manager(self) -> DownloadManager:
        if self._manager is None:
            if self._client is None:
                raise RuntimeError("网络客户端尚未就绪")
            self._manager = DownloadManager(
                self._config,
                on_event=self._on_manager_event,
                client=self._client,
            )
            await self._manager.start()
            self._bridge.ffmpegStateChanged.emit(self._manager.ffmpeg)
            self._applied_concurrency = self._config.max_concurrent_videos
        return self._manager

    def _on_manager_event(self, event: ManagerEvent) -> None:
        """在后台线程被调用，只做信号转发。"""
        if event.kind == "task_updated" and event.task is not None:
            self._bridge.taskUpdated.emit(event.task)
        elif event.kind == "task_removed" and event.task is not None:
            self._bridge.taskRemoved.emit(event.task.task_id)
        elif event.kind == "log":
            self._bridge.logMessage.emit(event.message, logging.INFO)
        elif event.kind == "finished":
            self._bridge.allFinished.emit(event.message)

    def _on_task_updated(self, task: DownloadTask) -> None:
        self.task_table.upsert(task)
        self._task_states[task.task_id] = task.state
        if task.output_path is not None:
            self._task_paths[task.task_id] = task.output_path
        self.tabs.setTabText(1, f"下载队列 ({len(self._task_states)})")
        self._refresh_stats()

    def _on_task_removed(self, task_id: str) -> None:
        self.task_table.remove(task_id)
        self._task_states.pop(task_id, None)
        self._task_paths.pop(task_id, None)
        if not self._task_states:
            self.tabs.setTabText(1, "下载队列")
        else:
            self.tabs.setTabText(1, f"下载队列 ({len(self._task_states)})")
        self._refresh_stats()

    def _on_all_finished(self, message: str) -> None:
        self._set_status(message)
        self.log_dock.show()

    def _on_task_action(self, task_id: str, action: str) -> None:
        if action == "open":
            self._open_folder(task_id)
            return
        self._runner.submit_safe(self._task_command(task_id, action))

    async def _task_command(self, task_id: str, action: str) -> None:
        await self._ensure_ready()
        manager = self._manager
        if manager is None:
            return
        if action == "retry":
            manager.retry(task_id)
        elif action == "pause":
            manager.pause(task_id)
        elif action == "resume":
            manager.resume(task_id)
        elif action == "cancel":
            manager.cancel(task_id)
        elif action == "remove":
            manager.remove_task(task_id)

    def _bulk(self, action: str) -> None:
        self._runner.submit_safe(self._bulk_command(action))

    async def _bulk_command(self, action: str) -> None:
        await self._ensure_ready()
        manager = self._manager
        if manager is None:
            return
        for task in manager.tasks:
            if action == "pause":
                manager.pause(task.task_id)
            elif action == "resume":
                manager.resume(task.task_id)
            elif action == "cancel":
                manager.cancel(task.task_id)

    def _on_clear_finished(self) -> None:
        if self._manager is not None:
            self._manager.clear_finished()

    def _on_drop_checked(self) -> None:
        self.result_tree.remove_checked()
        count = self.result_tree.count()
        self.tabs.setTabText(0, f"待下载 ({count})" if count else "待下载")

    # ------------------------------------------------------------------
    # 账号
    # ------------------------------------------------------------------
    def _on_qr_login(self) -> None:
        self._qr_cancelled = False
        self.account_panel.show_qr("正在获取二维码…")
        self._runner.submit_safe(self._qr_login_flow())

    def _on_cancel_qr(self) -> None:
        self._qr_cancelled = True
        self.account_panel.show_guest()

    async def _qr_login_flow(self) -> None:
        try:
            await self._ensure_ready()
            if self._auth is None:
                self._bridge.errorRaised.emit("账号模块尚未就绪")
                return

            session = await self._auth.create_qr_session()
            self._bridge.qrStateChanged.emit("等待扫码（二维码 3 分钟内有效）", session.image)

            while not self._qr_cancelled:
                state = await self._auth.poll_qr_session(session)
                if state is QrState.SUCCESS:
                    self._bridge.loginStateChanged.emit(self._auth.user)
                    self._bridge.infoRaised.emit(f"登录成功：{self._auth.display_name}")
                    return
                if state is QrState.EXPIRED:
                    self._bridge.qrStateChanged.emit(QrState.EXPIRED.label, None)
                    return
                if state is QrState.SCANNED:
                    self._bridge.qrStateChanged.emit(state.label, None)
                await asyncio.sleep(2.0)
        except BiliError as exc:
            self._bridge.errorRaised.emit(f"扫码登录失败：{exc}")
            self._bridge.loginStateChanged.emit({})
        except Exception as exc:  # noqa: BLE001
            log.exception("扫码登录异常")
            self._bridge.errorRaised.emit(f"扫码登录异常：{exc}")

    def _on_cookie_login(self, raw: str) -> None:
        self._runner.submit_safe(self._cookie_login(raw))

    async def _cookie_login(self, raw: str) -> None:
        try:
            await self._ensure_ready()
            if self._auth is None:
                self._bridge.errorRaised.emit("账号模块尚未就绪")
                return
            user = await self._auth.login_by_cookie(raw)
            self._bridge.loginStateChanged.emit(user)
            self._bridge.infoRaised.emit(f"登录成功：{user.get('uname')}")
        except BiliError as exc:
            self._bridge.errorRaised.emit(f"Cookie 登录失败：{exc}")

    def _on_logout(self) -> None:
        self._runner.submit_safe(self._logout())

    async def _logout(self) -> None:
        if self._auth is not None:
            await self._auth.logout()
        self._bridge.loginStateChanged.emit({})
        self._bridge.infoRaised.emit("已退出登录")

    def _on_login_state(self, user: object) -> None:
        data = user if isinstance(user, dict) else {}
        self.account_panel.set_user(data)
        if data:
            self.account_panel.clear_cookie_input()
            self._set_status(f"已登录：{data.get('uname')}（{self._config_tier(data)}）")
        else:
            self._set_status("未登录 · 仅能下载 480P")

    @staticmethod
    def _config_tier(user: dict) -> str:
        return "大会员" if user.get("is_vip") else "普通用户"

    def _on_qr_state(self, text: str, image: object) -> None:
        payload = image if isinstance(image, (bytes, bytearray)) else None
        self.account_panel.show_qr(text, payload)
        self._set_status(text)

    # ------------------------------------------------------------------
    # ffmpeg
    # ------------------------------------------------------------------
    def _on_ffmpeg_state(self, info: object) -> None:
        self.option_panel.set_ffmpeg(info if isinstance(info, FFmpegInfo) else None)

    def _on_download_ffmpeg(self) -> None:
        self.option_panel.set_ffmpeg_busy(True, "正在获取 ffmpeg…")
        self._runner.submit_safe(self._download_ffmpeg())

    async def _download_ffmpeg(self) -> None:
        try:
            info = await download_ffmpeg(
                report=lambda message, _fraction: self._bridge.logMessage.emit(
                    f"ffmpeg：{message}", logging.INFO
                )
            )
            self._config.ffmpeg_path = str(info.path)
            self._save_timer.start()
            if self._manager is not None:
                self._manager.reload_ffmpeg()
                info = self._manager.ffmpeg or info
            self._bridge.ffmpegStateChanged.emit(info)
            self._bridge.infoRaised.emit("ffmpeg 已就绪，DASH 高清模式可用")
        except Exception as exc:  # noqa: BLE001
            log.exception("获取 ffmpeg 失败")
            self._bridge.ffmpegStateChanged.emit(None)
            self._bridge.errorRaised.emit(f"获取 ffmpeg 失败：{exc}")

    def _on_pick_ffmpeg(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 ffmpeg 可执行文件", "", "可执行文件 (*.exe);;所有文件 (*)"
        )
        if not path:
            return
        self._config.ffmpeg_path = path
        self._save_timer.start()
        info = find_ffmpeg(Path(path))
        self._bridge.ffmpegStateChanged.emit(info)
        if info is None:
            self._bridge.errorRaised.emit("该文件不是可用的 ffmpeg")
        elif self._manager is not None:
            self._runner.submit_safe(self._reload_manager_ffmpeg())

    async def _reload_manager_ffmpeg(self) -> None:
        if self._manager is not None:
            self._manager.reload_ffmpeg()
            self._bridge.ffmpegStateChanged.emit(self._manager.ffmpeg)

    # ------------------------------------------------------------------
    # 配置与杂项
    # ------------------------------------------------------------------
    def _on_browse(self) -> None:
        current = self._config.download_dir
        chosen = QFileDialog.getExistingDirectory(self, "选择保存目录", current or str(Path.home()))
        if chosen:
            self.option_panel.set_download_dir(chosen)
            self._on_config_changed()

    def _on_config_changed(self) -> None:
        self.option_panel.apply_to(self._config)
        self._save_timer.start()
        if (
            self._manager is not None
            and self._config.max_concurrent_videos != self._applied_concurrency
        ):
            self._applied_concurrency = self._config.max_concurrent_videos
            self._runner.submit_safe(self._manager.restart_workers())

    def _persist_config(self) -> None:
        try:
            save_config(self._config)
        except Exception:  # noqa: BLE001
            log.exception("配置保存失败")

    def _on_toggle_theme(self) -> None:
        self._config.theme = "dark" if self._config.theme == "light" else "light"
        apply_theme(QApplication.instance(), self._config.theme)
        self._save_timer.start()

    def _open_folder(self, task_id: str) -> None:
        target = self._task_paths.get(task_id)
        if target is None:
            self._show_warning("该任务还没有输出文件")
            return
        folder = target if target.is_dir() else target.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _refresh_stats(self) -> None:
        states = list(self._task_states.values())
        total = len(states)
        completed = sum(1 for state in states if state is TaskState.COMPLETED)
        failed = sum(1 for state in states if state is TaskState.FAILED)
        active = sum(1 for state in states if state.is_active)

        self.stats_label.setText(
            f"共 {total} · 完成 {completed} · 失败 {failed} · 进行中 {active}"
        )
        finished = completed + failed
        self.global_bar.setValue(int(finished / total * 1000) if total else 0)

    def _set_status(self, message: str) -> None:
        self._status_hint.setText(message)

    def _append_log(self, message: str, level: int = logging.INFO) -> None:
        self.log_dock.append(message, level)

    def _on_log_message(self, message: str, level: int) -> None:
        self.log_dock.append(message, level)

    def _on_error(self, message: str) -> None:
        self._append_log(message, logging.ERROR)
        self.log_dock.show()
        self._set_status(message)

    def _on_info(self, message: str) -> None:
        self._append_log(message, logging.INFO)
        self._set_status(message)

    def _show_warning(self, message: str) -> None:
        QMessageBox.warning(self, "提示", message)

    # ------------------------------------------------------------------
    # 关闭
    # ------------------------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt 命名
        try:
            self.option_panel.apply_to(self._config)
            save_config(self._config)
        except Exception:  # noqa: BLE001
            log.exception("关闭前保存配置失败")

        if self._manager is not None:
            future = self._runner.submit_safe(self._manager.stop())
            if future is not None:
                try:
                    future.result(timeout=3.0)
                except Exception:  # noqa: BLE001
                    log.debug("调度器停止超时，直接退出")

        self._runner.stop(timeout=3.0)
        event.accept()
