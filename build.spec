# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（onedir）。

为什么用 onedir 而不是 onefile：
  onefile 每次启动都要把上百 MB 解压到临时目录，冷启动 3-6 秒；
  onedir 启动快、便于排查缺文件的问题，分发时打包成 zip 即可。

关于 ffmpeg：
  默认不内置（ffmpeg 静态包约 80MB），改为首次使用时在界面点
  「一键下载」获取，解压到 %APPDATA%/BiliDown/bin。
  需要完全离线可用的绿色版时，设置环境变量 BILIDOWN_BUNDLE_FFMPEG=1
  再执行打包：build.ps1 -BundleFFmpeg
"""

import os

BUNDLE_FFMPEG = os.environ.get("BILIDOWN_BUNDLE_FFMPEG") == "1"
APP_NAME = "B站视频下载器"

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("assets/app.ico", "assets")],
    # qrcode 的图像后端是运行时按名字导入的，静态分析看不到
    hiddenimports=["qrcode.image.pil"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 本项目完全用不到、但 PySide6 默认会拖进来的大块头
        "tkinter",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.QtQuickControls2",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtWebChannel",
        "PySide6.QtWebSockets",
        "PySide6.QtNetwork",
        "PySide6.QtSql",
        "PySide6.QtPrintSupport",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtGraphs",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DExtras",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtDesigner",
        "PySide6.QtHelp",
        "PySide6.QtUiTools",
        "PySide6.QtTest",
    ],
    noarchive=False,
    optimize=0,
)

#: 明确不需要的重量级文件
#: opengl32sw.dll 是 Qt 的软件 OpenGL 回退，只服务于 Qt Quick / WebEngine，
#: 纯 Widgets 程序用不到，却占了近 20MB。
DROP_FILES = {"opengl32sw.dll", "d3dcompiler_47.dll", "qtwebenginecore.dll"}


def _keep(entry) -> bool:
    name = str(entry[0]).lower()
    if not BUNDLE_FFMPEG and "ffmpeg" in name:
        return False
    return os.path.basename(name) not in DROP_FILES


a.datas = [item for item in a.datas if _keep(item)]
a.binaries = [item for item in a.binaries if _keep(item)]

#: 单文件模式：只有一个 exe，便于直接下载使用。
#: 代价是每次启动都要把内容解压到临时目录，冷启动慢 3-6 秒，
#: 因此发布版同时提供 onedir 压缩包（推荐）与单文件 exe。
ONEFILE = os.environ.get("BILIDOWN_ONEFILE") == "1"

pyz = PYZ(a.pure)

_exe_kwargs = dict(
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["assets/app.ico"],
)

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], **_exe_kwargs)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **_exe_kwargs)
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=APP_NAME,
    )
