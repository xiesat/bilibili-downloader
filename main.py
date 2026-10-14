"""B站视频下载器 —— 程序入口。

用法::

    python main.py                 # 启动图形界面
    python -m bilidown             # 等价写法
    python main.py <视频链接>       # 命令行模式（P3 阶段提供）
"""

from __future__ import annotations

import sys
from pathlib import Path

# 支持在项目根目录直接运行本文件
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from bilidown.app import main

if __name__ == "__main__":
    raise SystemExit(main())
