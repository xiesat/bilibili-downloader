"""解析结果列表：勾选要下载的条目。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from ...core.metadata import MediaEntry
from ...util.filename import format_duration

__all__ = ["ResultTree"]

COLUMNS = ("标题", "UP主", "分P", "时长", "所属合集")


class ResultTree(QTreeWidget):
    """解析结果。每个条目对应一个可下载的分 P。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setColumnCount(len(COLUMNS))
        self.setHeaderLabels(list(COLUMNS))
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        header = self.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for index in range(1, len(COLUMNS)):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(False)

        self._entries: list[MediaEntry] = []

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------
    def set_entries(self, entries: list[MediaEntry]) -> None:
        """用新的解析结果替换列表，默认全部勾选。"""
        self.clear()
        self._entries = list(entries)

        for entry in self._entries:
            item = QTreeWidgetItem(self)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked)
            item.setText(0, entry.display_title)
            item.setToolTip(0, entry.display_title)
            item.setText(1, entry.video.owner or "—")
            if entry.video.is_multi_part:
                item.setText(2, f"P{entry.page.page}/{len(entry.video.pages)}")
            else:
                item.setText(2, "—")
            duration = entry.page.duration or entry.video.duration
            item.setText(3, format_duration(duration) if duration else "—")
            item.setText(4, entry.video.season_title or "—")

        if self._entries:
            self.setCurrentItem(self.topLevelItem(0))

    def entries(self) -> list[MediaEntry]:
        """全部条目。"""
        return list(self._entries)

    def checked_entries(self) -> list[MediaEntry]:
        """仅返回被勾选的条目。"""
        selected: list[MediaEntry] = []
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            if item is not None and item.checkState(0) == Qt.CheckState.Checked:
                if index < len(self._entries):
                    selected.append(self._entries[index])
        return selected

    def set_all_checked(self, checked: bool) -> None:
        """全选 / 全不选。"""
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            if item is not None:
                item.setCheckState(0, state)

    def remove_checked(self) -> None:
        """移除被勾选的条目。"""
        keep: list[MediaEntry] = []
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            if item is None or index >= len(self._entries):
                continue
            if item.checkState(0) == Qt.CheckState.Checked:
                continue
            keep.append(self._entries[index])
        self.set_entries(keep)

    def clear_entries(self) -> None:
        """清空列表。"""
        self.clear()
        self._entries = []

    def count(self) -> int:
        """条目数。"""
        return len(self._entries)
