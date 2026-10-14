"""B站视频下载器 —— 现代化重构版。

分层结构::

    bilidown.core      接口与解析（零 GUI 依赖）
    bilidown.download  下载引擎与任务调度（零 GUI 依赖）
    bilidown.ui        PySide6 界面
    bilidown.util      通用工具
"""

from __future__ import annotations

__version__ = "2.0.0"
__all__ = ["__version__"]
