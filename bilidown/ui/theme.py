"""界面主题：统一的配色、字号与 QSS 样式表。

配色取自 B 站视觉规范：主色用品牌粉，强调色用品牌蓝。
所有控件样式集中在这里，避免散落在各个视图中。
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

__all__ = ["apply_theme", "COLORS", "LIGHT_QSS", "DARK_QSS", "THEMES"]

#: 浅色主题调色板
COLORS = {
    "primary": "#FB7299",
    "primary_hover": "#FF85A5",
    "primary_soft": "#FFF0F5",
    "accent": "#00AEEC",
    "bg": "#F5F6F7",
    "card": "#FFFFFF",
    "border": "#E3E5E7",
    "border_strong": "#D0D3D6",
    "text": "#18191C",
    "text_secondary": "#61666D",
    "text_muted": "#9499A0",
    "success": "#67C23A",
    "warning": "#E6A23C",
    "danger": "#F56C6C",
}

_FONT_STACK = '"Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif'

LIGHT_QSS = """QWidget {
    font-family: FONT_STACK;
    font-size: 13px;
    color: #18191C;
}
QMainWindow, #CentralArea, #TopArea { background: #F5F6F7; }
QScrollArea { border: none; background: transparent; }

QFrame#Card {
    background: #FFFFFF;
    border: 1px solid #E3E5E7;
    border-radius: 10px;
}
QLabel#CardTitle { font-size: 14px; font-weight: 600; color: #18191C; }

QGroupBox {
    background: #FFFFFF;
    border: 1px solid #E3E5E7;
    border-radius: 10px;
    margin-top: 12px;
    padding: 12px 12px 10px 12px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 6px;
    color: #18191C;
}

QPushButton {
    background: #FFFFFF;
    border: 1px solid #D0D3D6;
    border-radius: 8px;
    padding: 6px 14px;
    min-height: 20px;
}
QPushButton:hover { border-color: #FB7299; color: #FB7299; }
QPushButton:pressed { background: #FFF0F5; }
QPushButton:disabled { color: #C9CCD0; border-color: #E9EBED; background: #FAFAFA; }

QPushButton#Primary {
    background: #FB7299; border: 1px solid #FB7299; color: #FFFFFF;
    font-weight: 600; padding: 8px 22px; border-radius: 8px;
}
QPushButton#Primary:hover { background: #FF85A5; border-color: #FF85A5; color: #FFFFFF; }
QPushButton#Primary:pressed { background: #E85F86; }
QPushButton#Primary:disabled { background: #F5C2D2; border-color: #F5C2D2; color: #FFFFFF; }

QPushButton#Ghost { background: transparent; border: none; color: #00AEEC; padding: 4px 8px; }
QPushButton#Ghost:hover { color: #FB7299; text-decoration: underline; }

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {
    background: #FFFFFF;
    border: 1px solid #D0D3D6;
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: #FB7299;
    selection-color: #FFFFFF;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus {
    border-color: #FB7299;
}
QLineEdit[readOnly="true"] { background: #F7F8FA; color: #61666D; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background: #FFFFFF; border: 1px solid #E3E5E7; border-radius: 8px;
    selection-background-color: #FB7299; selection-color: #FFFFFF; outline: none;
}
QSpinBox::up-button, QSpinBox::down-button {
    width: 18px; border: none; background: transparent; subcontrol-origin: border;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #FFF0F5; }

QTreeWidget, QTreeView, QTableWidget, QTableView {
    background: #FFFFFF;
    border: 1px solid #E3E5E7;
    border-radius: 10px;
    outline: none;
    alternate-background-color: #FAFBFC;
}
QTreeWidget::item, QTreeView::item { height: 28px; }
QTreeWidget::item:selected, QTreeView::item:selected { background: #FFF0F5; color: #18191C; }
QTreeWidget::item:hover, QTreeView::item:hover { background: #F7F8FA; }
QHeaderView::section {
    background: #F7F8FA; border: none; border-bottom: 1px solid #E3E5E7;
    padding: 7px 8px; font-weight: 600; color: #61666D;
}
QHeaderView::section:first { border-top-left-radius: 10px; }
QHeaderView::section:last { border-top-right-radius: 10px; }

QProgressBar {
    border: none; border-radius: 5px; background: #EDEFF2;
    height: 10px; text-align: center; color: transparent;
}
QProgressBar::chunk { border-radius: 5px; background: #FB7299; }
QProgressBar#Success::chunk { background: #67C23A; }
QProgressBar#Danger::chunk { background: #F56C6C; }

QTabWidget::pane {
    border: 1px solid #E3E5E7; border-radius: 10px; background: #FFFFFF;
}
QTabBar::tab {
    background: transparent; padding: 8px 18px; border: none; color: #61666D;
}
QTabBar::tab:selected { color: #FB7299; border-bottom: 2px solid #FB7299; font-weight: 600; }
QTabBar::tab:hover { color: #FB7299; }

QStatusBar { background: #FFFFFF; border-top: 1px solid #E3E5E7; color: #61666D; }
QStatusBar::item { border: none; }

QLabel#Hint { color: #9499A0; font-size: 12px; }
QLabel#Success { color: #67C23A; }
QLabel#Warning { color: #E6A23C; }
QLabel#Danger { color: #F56C6C; }
QLabel#SectionTitle { font-size: 15px; font-weight: 600; }

QCheckBox { spacing: 6px; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #D0D3D6; border-radius: 4px; background: #FFFFFF; }
QCheckBox::indicator:checked { background: #FB7299; border-color: #FB7299; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #D0D3D6; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #B8BCC0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #D0D3D6; border-radius: 5px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QDockWidget { titlebar-close-icon: none; color: #61666D; }
QDockWidget::title {
    background: #F7F8FA; padding: 7px 12px;
    border-bottom: 1px solid #E3E5E7; border-top-left-radius: 10px; border-top-right-radius: 10px;
}

QMenu { background: #FFFFFF; border: 1px solid #E3E5E7; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 6px 22px; border-radius: 6px; }
QMenu::item:selected { background: #FFF0F5; color: #FB7299; }

QToolTip { background: #18191C; color: #FFFFFF; border: none; border-radius: 6px; padding: 5px 8px; }
"""

DARK_QSS = """QWidget {
    font-family: FONT_STACK;
    font-size: 13px;
    color: #E8E8EA;
}
QMainWindow, #CentralArea, #TopArea { background: #17181A; }
QScrollArea { border: none; background: transparent; }
QFrame#Card { background: #1F2022; border: 1px solid #2E3033; border-radius: 10px; }
QLabel#CardTitle { font-size: 14px; font-weight: 600; color: #E8E8EA; }
QGroupBox {
    background: #1F2022; border: 1px solid #2E3033; border-radius: 10px;
    margin-top: 12px; padding: 12px 12px 10px 12px; font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 14px; padding: 0 6px; color: #E8E8EA;
}
QPushButton {
    background: #26282B; border: 1px solid #3A3D41; border-radius: 8px;
    padding: 6px 14px; color: #E8E8EA; min-height: 20px;
}
QPushButton:hover { border-color: #FB7299; color: #FB7299; }
QPushButton:disabled { color: #5A5D61; border-color: #2E3033; background: #1D1E20; }
QPushButton#Primary {
    background: #FB7299; border: 1px solid #FB7299; color: #FFFFFF;
    font-weight: 600; padding: 8px 22px;
}
QPushButton#Primary:hover { background: #FF85A5; }
QPushButton#Primary:disabled { background: #6B3A48; border-color: #6B3A48; color: #C9A2AD; }
QPushButton#Ghost { background: transparent; border: none; color: #00AEEC; padding: 4px 8px; }
QPushButton#Ghost:hover { color: #FB7299; }
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {
    background: #26282B; border: 1px solid #3A3D41; border-radius: 8px;
    padding: 6px 10px; color: #E8E8EA;
    selection-background-color: #FB7299; selection-color: #FFFFFF;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #FB7299; }
QLineEdit[readOnly="true"] { background: #1D1E20; color: #9BA0A6; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background: #26282B; border: 1px solid #3A3D41;
    selection-background-color: #FB7299; selection-color: #FFFFFF; outline: none;
}
QSpinBox::up-button, QSpinBox::down-button {
    width: 18px; border: none; background: #303338; subcontrol-origin: border;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #3A3D41; }
QTreeWidget, QTreeView, QTableWidget, QTableView {
    background: #1F2022; border: 1px solid #2E3033; border-radius: 10px;
    outline: none; alternate-background-color: #232427;
}
QTreeWidget::item, QTreeView::item { height: 28px; }
QTreeWidget::item:selected, QTreeView::item:selected { background: #3A2A31; color: #E8E8EA; }
QHeaderView::section {
    background: #232427; border: none; border-bottom: 1px solid #2E3033;
    padding: 7px 8px; font-weight: 600; color: #9BA0A6;
}
QProgressBar { border: none; border-radius: 5px; background: #2E3033; height: 10px; color: transparent; }
QProgressBar::chunk { border-radius: 5px; background: #FB7299; }
QProgressBar#Success::chunk { background: #67C23A; }
QProgressBar#Danger::chunk { background: #F56C6C; }
QTabWidget::pane { border: 1px solid #2E3033; border-radius: 10px; background: #1F2022; }
QTabBar::tab { background: transparent; padding: 8px 18px; border: none; color: #9BA0A6; }
QTabBar::tab:selected { color: #FB7299; border-bottom: 2px solid #FB7299; font-weight: 600; }
QStatusBar { background: #1F2022; border-top: 1px solid #2E3033; color: #9BA0A6; }
QLabel#Hint { color: #7C8085; font-size: 12px; }
QLabel#Success { color: #67C23A; }
QLabel#Warning { color: #E6A23C; }
QLabel#Danger { color: #F56C6C; }
QLabel#SectionTitle { font-size: 15px; font-weight: 600; }
QCheckBox { spacing: 6px; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #3A3D41; border-radius: 4px; background: #26282B; }
QCheckBox::indicator:checked { background: #FB7299; border-color: #FB7299; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #3A3D41; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #4A4E53; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QDockWidget { color: #9BA0A6; }
QDockWidget::title {
    background: #232427; padding: 7px 12px; border-bottom: 1px solid #2E3033;
}
QMenu { background: #26282B; border: 1px solid #3A3D41; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 6px 22px; border-radius: 6px; }
QMenu::item:selected { background: #3A2A31; color: #FB7299; }
QToolTip { background: #E8E8EA; color: #17181A; border: none; border-radius: 6px; padding: 5px 8px; }
"""

THEMES = {"light": LIGHT_QSS, "dark": DARK_QSS}


def apply_theme(app: QApplication, name: str = "light") -> str:
    """把主题样式应用到整个应用，返回实际使用的主题名。"""
    key = name if name in THEMES else "light"
    app.setStyleSheet(THEMES[key].replace("FONT_STACK", _FONT_STACK))
    return key
