"""内置自检：验证运行环境（尤其是打包后）是否完整。

打包版是窗口程序（console=False），没有标准输出可以看，
所以自检把结果写进 JSON 文件，并额外截一张界面图。
这样"双击没反应"这类问题可以一次性定位到具体缺了什么。

用法::

    B站视频下载器.exe --selftest [报告文件]
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

__all__ = ["run_selftest"]


def run_selftest(outfile: Path) -> int:
    """执行全部自检项，把报告写到 outfile，返回进程退出码。"""
    report: dict[str, object] = {
        "frozen": bool(getattr(sys, "frozen", False)),
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "meipass": getattr(sys, "_MEIPASS", None),
        "checks": {},
        "errors": [],
    }
    checks: dict[str, object] = report["checks"]  # type: ignore[assignment]
    errors: list[str] = report["errors"]  # type: ignore[assignment]

    def check(name: str, func) -> None:
        try:
            checks[name] = func()
        except Exception as exc:  # noqa: BLE001 - 自检要吞掉所有异常并记录
            checks[name] = f"FAIL: {exc}"
            errors.append(f"{name}: {exc}\n{traceback.format_exc()}")

    def _imports() -> str:
        from bilidown import core, download, ui, util  # noqa: F401
        from bilidown.core import auth, client, credentials, metadata, parser, playurl  # noqa: F401
        from bilidown.download import engine, manager, mux  # noqa: F401
        from bilidown.ui import app, bridge, theme  # noqa: F401
        from bilidown.ui.views import (  # noqa: F401
            account_panel, card, input_panel, log_dock, option_panel, result_tree, task_table,
        )
        return "ok"

    def _version() -> str:
        from bilidown import __version__
        return __version__

    def _parser() -> dict:
        from bilidown.core.parser import parse_lines
        valid, invalid = parse_lines("BV1GJ411x7h7\nav170001\nb23.tv/abc\n这不是链接")
        return {
            "valid": [item.kind.value for item in valid],
            "invalid": len(invalid),
            "bvid": valid[0].bvid if valid else "",
        }

    def _filename() -> dict:
        from bilidown.util.filename import sanitize
        return {"sanitize": sanitize('a<b>:c/d\\e|f?g*h'), "reserved": sanitize("CON")}

    def _credentials() -> dict:
        from bilidown.core.credentials import dpapi_available
        return {"dpapi": dpapi_available()}

    def _qrcode() -> dict:
        from bilidown.core.auth import render_qr
        data = render_qr("https://example.invalid/login")
        return {"bytes": len(data), "png": data[:4] == b"\x89PNG"}

    def _pillow() -> str:
        import PIL
        return str(PIL.__version__)

    def _qrcode_module() -> str:
        import qrcode
        return str(getattr(qrcode, "__version__", "installed"))

    def _ffmpeg() -> dict:
        from bilidown.util.ffmpeg import find_ffmpeg, probe_version
        info = find_ffmpeg()
        if info is None:
            return {"found": False}
        return {"found": True, "source": info.source, "path": str(info.path),
                "version": (info.version or probe_version(info.path))[:60]}

    def _config() -> dict:
        import tempfile
        from bilidown.config import AppConfig, load_config, save_config
        target = Path(tempfile.gettempdir()) / "bilidown_selftest_config.json"
        config = AppConfig(chunks_per_video=6).normalize()
        save_config(config, target)
        loaded = load_config(target)
        target.unlink(missing_ok=True)
        return {"roundtrip": loaded.chunks_per_video == 6, "cookie_persisted": "cookie" in config.to_dict()}

    def _gui() -> dict:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication

        from bilidown.ui.app import MainWindow

        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.show()

        deadline = time.time() + 10.0
        while time.time() < deadline and not window._bootstrapped:
            app.processEvents()
            time.sleep(0.02)
        for _ in range(40):
            app.processEvents()
            time.sleep(0.01)

        shot = outfile.with_name(outfile.stem + "_window.png")
        saved = window.grab().save(str(shot))
        window._runner.stop(2.0)
        return {"screenshot": str(shot), "saved": bool(saved),
                "bootstrapped": window._bootstrapped,
                "size": [window.width(), window.height()]}

    check("imports", _imports)
    check("version", _version)
    check("parser", _parser)
    check("filename", _filename)
    check("credentials", _credentials)
    check("qrcode_render", _qrcode)
    check("pillow", _pillow)
    check("qrcode_module", _qrcode_module)
    check("ffmpeg", _ffmpeg)
    check("config", _config)
    check("gui", _gui)

    report["ok"] = not errors
    outfile.parent.mkdir(parents=True, exist_ok=True)
    outfile.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if not errors else 1
