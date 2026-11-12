"""Build steps for Media Manglers' own tools in the packaged application folder (installer plan, Stages 4 and 5).

``Build-PackagedRuntime.ps1`` runs these with the build's Python 3.12.10, the same version as our own Python, so
the bytecode it compiles is the bytecode our Python reads. Nothing here uses pip or the network.

    python packaged_runtime.py whisper-wheel --sdist F --setuptools W --work DIR
        Turn the pinned openai-whisper source into a wheel with the pinned setuptools' own build backend.
    python packaged_runtime.py unpack --wheel W --into DIR
        Unpack a wheel the way the first-launch setup does: every file checked against the wheel's RECORD.
    python packaged_runtime.py ffmpeg-check --ffmpeg EXE --needs JSON [--report FILE]
        Check that FFmpeg has every encoder, decoder, filter and format the app needs.
    python packaged_runtime.py addons-hook --into SITE_PACKAGES
        Write the start-up hook that gives our own Python its downloaded speech libraries.
    python packaged_runtime.py stdlib-leave-out --zip PYTHON312_ZIP --member NAME [--member NAME ...]
        Rewrite the standard library's zip without the named, unused members (same order, same bytes otherwise).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers.core.private_runtime import write_addons_hook  # noqa: E402
from media_manglers.core.speech_setup import unpack_wheel  # noqa: E402

# The Whisper source's own release date, so the wheel's file times do not depend on the day of the build.
WHEEL_DATE_EPOCH = "1750809600"


def _fresh(folder: Path) -> Path:
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    return folder


def whisper_wheel(sdist: Path, setuptools_wheel: Path, work: Path) -> Path:
    """The openai-whisper wheel, built from ``sdist`` by ``setuptools_wheel``'s build backend, in a Python of its
    own that sees only that setuptools."""

    work, sdist, setuptools_wheel = Path(work).resolve(), Path(sdist).resolve(), Path(setuptools_wheel).resolve()
    source = _fresh(work / "whisper-src")
    with tarfile.open(sdist) as archive:
        archive.extractall(source, filter="data")
    roots = [item for item in source.iterdir() if item.is_dir()]
    if len(roots) != 1 or not (roots[0] / "setup.py").is_file() and not (roots[0] / "pyproject.toml").is_file():
        raise SystemExit(f"The Whisper source {sdist.name} does not have the expected layout.")
    library = _fresh(work / "setuptools-lib")
    unpack_wheel(setuptools_wheel, library, ())
    out = _fresh(work / "whisper-wheel")
    code = ("import os, sys; sys.path.insert(0, sys.argv[1]); os.chdir(sys.argv[2]); "
            "import setuptools.build_meta as backend; print(backend.build_wheel(sys.argv[3]))")
    env = {key: value for key, value in os.environ.items() if not key.startswith("PYTHON")}
    env["SOURCE_DATE_EPOCH"] = WHEEL_DATE_EPOCH
    subprocess.run([sys.executable, "-I", "-c", code, str(library), str(roots[0]), str(out)], check=True, env=env,
                   cwd=str(roots[0]), stdout=subprocess.DEVNULL)
    wheels = list(out.glob("openai_whisper-*.whl"))
    if len(wheels) != 1:
        raise SystemExit("The Whisper wheel was not built.")
    return wheels[0]


def stdlib_leave_out(zip_path: Path, members: list[str]) -> list[str]:
    """Rewrite ``zip_path`` without ``members``; every other member is copied unchanged, in order. Returns what was
    left out (a name that is not there is simply not there)."""

    import zipfile  # noqa: PLC0415

    zip_path = Path(zip_path)
    partial = zip_path.with_name(zip_path.name + ".partial")
    dropped: list[str] = []
    with zipfile.ZipFile(zip_path) as source, zipfile.ZipFile(partial, "w") as target:
        for info in source.infolist():
            if info.filename in members:
                dropped.append(info.filename)
                continue
            target.writestr(info, source.read(info), compress_type=info.compress_type)
    os.replace(partial, zip_path)
    return dropped


# FFmpeg ---------------------------------------------------------------------------------------------------


_LISTS = {"encoders": "-encoders", "decoders": "-decoders", "filters": "-filters", "muxers": "-muxers",
          "demuxers": "-demuxers", "devices": "-devices"}


def _names(text: str, kind: str) -> set[str]:
    """The names in one of FFmpeg's -encoders/-filters/... lists."""

    names: set[str] = set()
    started = kind == "filters"
    for line in text.splitlines():
        if not started:
            started = line.strip().startswith("--") or line.strip() == "------"
            continue
        parts = line.split()
        if kind == "filters":
            # " T.. drawtext          V->V       Draw text..."
            if len(parts) >= 3 and re.fullmatch(r"[TSC.|]{2,3}", parts[0]) and re.fullmatch(r"[\w-]+", parts[1]):
                names.add(parts[1])
        elif kind in {"muxers", "demuxers", "devices"}:
            # " E  mp4             MP4 (MPEG-4 Part 14)" ; " DE mov,mp4,m4a,..."
            if len(parts) >= 2 and re.fullmatch(r"[DE ]{1,2}d?", parts[0]):
                names.update(parts[1].split(","))
        elif len(parts) >= 2 and re.fullmatch(r"[VASDFXB.]{6}", parts[0]):
            names.add(parts[1])
    return names


def ffmpeg_capabilities(ffmpeg: Path) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for kind, flag in _LISTS.items():
        completed = subprocess.run([str(ffmpeg), "-hide_banner", flag], capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=60, check=False)
        if completed.returncode != 0:
            raise SystemExit(f"{ffmpeg} {flag} failed: {completed.stderr.strip()[:300]}")
        found[kind] = _names(completed.stdout, kind)
    version = subprocess.run([str(ffmpeg), "-hide_banner", "-version"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60, check=False).stdout
    found["configuration"] = set(re.findall(r"--enable-[\w-]+", version))
    found["version"] = {version.splitlines()[0] if version else ""}
    return found


def ffmpeg_check(ffmpeg: Path, needs_file: Path) -> dict[str, object]:
    """Every required name in ``needs_file`` must be in FFmpeg's own lists; optional ones are reported only."""

    needs = json.loads(Path(needs_file).read_text(encoding="utf-8"))
    found = ffmpeg_capabilities(ffmpeg)
    missing: dict[str, list[str]] = {}
    optional_missing: dict[str, list[str]] = {}
    for kind in (*_LISTS, "configuration"):
        for item in needs.get(kind, []):
            name, required = (item["name"], bool(item.get("required", True))) if isinstance(item, dict) else (item, True)
            if name not in found[kind]:
                (missing if required else optional_missing).setdefault(kind, []).append(name)
    return {"ffmpeg": str(ffmpeg), "version": next(iter(found["version"])), "missing": missing,
            "optional_missing": optional_missing, "ok": not missing,
            "checked": {kind: len(needs.get(kind, [])) for kind in (*_LISTS, "configuration")}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    wheel = commands.add_parser("whisper-wheel")
    wheel.add_argument("--sdist", required=True)
    wheel.add_argument("--setuptools", required=True)
    wheel.add_argument("--work", required=True)
    unpack = commands.add_parser("unpack")
    unpack.add_argument("--wheel", required=True)
    unpack.add_argument("--into", required=True)
    check = commands.add_parser("ffmpeg-check")
    check.add_argument("--ffmpeg", required=True)
    check.add_argument("--needs", required=True)
    check.add_argument("--report", default="")
    hook = commands.add_parser("addons-hook")
    hook.add_argument("--into", required=True)
    leave = commands.add_parser("stdlib-leave-out")
    leave.add_argument("--zip", required=True)
    leave.add_argument("--member", action="append", default=[])
    args = parser.parse_args(argv)
    if args.command == "addons-hook":
        print(write_addons_hook(Path(args.into)))
        return 0
    if args.command == "stdlib-leave-out":
        dropped = stdlib_leave_out(Path(args.zip), list(args.member))
        print(f"left out of {Path(args.zip).name}: {', '.join(dropped) or 'nothing'}")
        return 0
    if args.command == "whisper-wheel":
        print(whisper_wheel(Path(args.sdist), Path(args.setuptools), Path(args.work)))
        return 0
    if args.command == "unpack":
        written = unpack_wheel(Path(args.wheel), Path(args.into), ())
        print(f"{len(written)} files from {Path(args.wheel).name}")
        return 0
    result = ffmpeg_check(Path(args.ffmpeg), Path(args.needs))
    text = json.dumps(result, indent=2)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
