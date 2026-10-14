"""下载队列表格：状态、进度与右键操作。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
    QProgressBar,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from ...models import DownloadTask, TaskState
from ...util.filename import human_size, human_speed

__all__ = ["TaskTable"]

COLUMNS = ("标题", "状态", "进度", "速度", "大小")

#: 状态对应的文字颜色
STATE_COLORS = {
    TaskState.COMPLETED: "#67C23A",
    TaskState.FAILED: "#F56C6C",
    TaskState.CANCELLED: "#9499A0",
    TaskState.PAUSED: "#E6A23C",
    TaskState.DOWNLOADING: "#00AEEC",
    TaskState.MUXING: "#00AEEC",
    TaskState.PARSING: "#9499A0",
    TaskState.QUEUED: "#9499A0",
    TaskState.PENDING: "#9499A0",
}

_BAR_SUCCESS = "QProgressBar::chunk { background: #67C23A; border-radius: 5px; }"
_BAR_DANGER = "QProgressBar::chunk { background: #F56C6C; border-radius: 5px; }"
_BAR_PAUSED = "QProgressBar::chunk { background: #E6A23C; border-radius: 5px; }"

#: 右键菜单项：(动作标识, 文案)
MENU_ITEMS = (
    ("open", "打开所在文件夹"),
    ("retry", "重试"),
    ("pause", "暂停"),
    ("resume", "恢复"),
    ("cancel", "取消"),
    ("remove", "从列表移除"),
)


class TaskTable(QTreeWidget):
    """下载队列。只负责展示与发出动作意图。"""

    actionRequested = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setColumnCount(len(COLUMNS))
        self.setHeaderLabels(list(COLUMNS))
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

        header = self.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for index in range(1, len(COLUMNS)):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(False)

        self._rows: dict[str, QTreeWidgetItem] = {}
        self._bars: dict[str, QProgressBar] = {}

    # ------------------------------------------------------------------
    # 数据操作
    # ------------------------------------------------------------------
    def upsert(self, task: DownloadTask) -> None:
        """新增或更新一行。"""
        item = self._rows.get(task.task_id)
        if item is None:
            item = QTreeWidgetItem(self)
            item.setData(0, Qt.ItemDataRole.UserRole, task.task_id)
            bar = QProgressBar(self)
            bar.setRange(0, 1000)
            bar.setTextVisible(False)
            bar.setFixedHeight(12)
            self.setItemWidget(item, 2, bar)
            self._rows[task.task_id] = item
            self._bars[task.task_id] = bar

        item.setText(0, task.display_title)
        tip = task.display_title
        if task.error:
            tip = f"{tip}\n错误：{task.error}"
        if task.output_path:
            tip = f"{tip}\n输出：{task.output_path}"
        item.setToolTip(0, tip)
        item.setData(0, Qt.ItemDataRole.UserRole + 1, task.state.value)

        item.setText(1, task.state.label)
        item.setForeground(1, QColor(STATE_COLORS.get(task.state, "#61666D")))

        bar = self._bars[task.task_id]
        bar.setValue(int(task.progress * 1000))
        if task.state is TaskState.COMPLETED:
            bar.setStyleSheet(_BAR_SUCCESS)
        elif task.state is TaskState.FAILED:
            bar.setStyleSheet(_BAR_DANGER)
        elif task.state is TaskState.PAUSED:
            bar.setStyleSheet(_BAR_PAUSED)
        else:
            bar.setStyleSheet("")

        item.setText(3, human_speed(task.speed) if task.state is TaskState.DOWNLOADING else "—")
        if task.total > 0:
            item.setText(4, f"{human_size(task.downloaded)} / {human_size(task.total)}")
        elif task.downloaded > 0:
            item.setText(4, human_size(task.downloaded))
        else:
            item.setText(4, "—")

    def remove(self, task_id: str) -> None:
        """移除一行。"""
        item = self._rows.pop(task_id, None)
        self._bars.pop(task_id, None)
        if item is not None:
            index = self.indexOfTopLevelItem(item)
            if index >= 0:
                self.takeTopLevelItem(index)

    def clear_all(self) -> None:
        """清空全部行。"""
        self._rows.clear()
        self._bars.clear()
        self.clear()

    def row_count(self) -> int:
        """当前行数。"""
        return len(self._rows)

    # ------------------------------------------------------------------
    # 右键菜单
    # ------------------------------------------------------------------
    def _show_menu(self, position) -> None:
        item = self.itemAt(position)
        if item is None:
            return
        task_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        state_value = str(item.data(0, Qt.ItemDataRole.UserRole + 1) or "")
        if not task_id:
            return

        try:
            state = TaskState(state_value)
        except ValueError:
            state = TaskState.PENDING

        allowed = self._allowed_actions(state)
        if not allowed:
            return

        menu = QMenu(self)
        for key, label in MENU_ITEMS:
            if key not in allowed:
                continue
            action = menu.addAction(label)
            action.setData(key)

        chosen = menu.exec(self.viewport().mapToGlobal(position))
        if chosen is not None:
            self.actionRequested.emit(task_id, str(chosen.data()))

    @staticmethod
    def _allowed_actions(state: TaskState) -> set[str]:
        """按任务状态筛选可用的菜单项。"""
        allowed: set[str] = {"remove"}
        if state is TaskState.COMPLETED:
            allowed.add("open")
        if state in (TaskState.FAILED, TaskState.CANCELLED):
            allowed.add("retry")
        if state is TaskState.PAUSED:
            allowed.add("resume")
        elif not state.is_terminal:
            allowed.add("pause")
            allowed.add("cancel")
        return allowed
