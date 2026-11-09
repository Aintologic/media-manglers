import os
from pathlib import Path


repo_root = Path(SPECPATH).resolve().parents[1]
entry_point = repo_root / "tools" / "gui" / "video_mangler_workbench_entry.py"
icon_path = repo_root / "assets" / "Video Mangler.ico"
version_path = repo_root / "tools" / "gui" / "VideoManglerWorkbench.version.txt"
manifest_path = repo_root / "tools" / "gui" / "VideoManglerWorkbench.manifest"
build_identity_path = Path(os.environ["MEDIA_MANGLERS_BUILD_IDENTITY_PATH"])
if not build_identity_path.is_file():
    raise RuntimeError(f"Generated build identity was not found: {build_identity_path}")

a = Analysis(
    [str(entry_point)],
    pathex=[str(repo_root / "src")],
    binaries=[],
    # 237: the theme's own small images (drop-down arrows, the tick in a ticked box).
    datas=[(str(build_identity_path), "media_manglers_workbench"),
           (str(repo_root / "src" / "media_manglers_workbench" / "assets"), "media_manglers_workbench/assets")],
    # 220: the raw bin library page opens its SQLite database in the Workbench process itself.
    hiddenimports=["media_manglers.core.review_queue", "media_manglers.core.raw_bin_library", "sqlite3"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # The built-in player reads the spotter phrase list from
        # media_manglers.core.voice_track, which imports these inside the
        # functions that run voice detection. The Workbench never runs those in
        # its own process (the backend's Python does), and PyInstaller follows
        # such imports, so without this the package grows by tens of megabytes
        # for code it cannot reach.
        "numpy",
        "torch",
        "whisper",
        "PySide6.QtBluetooth",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtLocation",
        "PySide6.QtNetworkAuth",
        "PySide6.QtPdf",
        "PySide6.QtPositioning",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtRemoteObjects",
        "PySide6.QtScxml",
        "PySide6.QtSensors",
        "PySide6.QtSerialPort",
        "PySide6.QtSpatialAudio",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "PySide6.QtWebChannel",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebSockets",
    ],
    noarchive=False,
    optimize=0,
)
# 138: binaries the Qt hooks bring in that the package leaves out. Qt Virtual Keyboard is offered
# only under the GPL-3.0, not the LGPL, and the Workbench never uses it. Qt's OpenSSL TLS backend
# would ship whatever OpenSSL the build PC has on PATH; without it Qt uses Windows' own TLS.
LEFT_OUT_BINARIES = {
    "qt6virtualkeyboard.dll",
    "qtvirtualkeyboardplugin.dll",
    "qopensslbackend.dll",
    "libssl-3-x64.dll",
    "libcrypto-3-x64.dll",
}
a.binaries = [entry for entry in a.binaries if Path(entry[0]).name.lower() not in LEFT_OUT_BINARIES]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VideoManglerWorkbench",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(icon_path),
    version=str(version_path),
    manifest=str(manifest_path),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="VideoManglerWorkbench",
)
