"""Technical check of a rendered video (150).

Separate from the editorial review: this only says whether the file is technically fit to watch
and upload. Checks: container, codecs, frame size and rate, audio format, video and audio the same
length, the length the timeline expects, a full decode with no errors, integrated loudness and
true peak, black stretches and dead air. Frozen pictures are reported (a results screen is
legitimately still) but do not fail the check.

226: the expected frame size and rate are the ones the render used, from its render report (the
recording's own frame rate, up to 60, and a validation run's size), or the ones a request gives;
without either, the profile's (1920x1080 at 60, 1280x720 at 30). The rate may be off by 0.01 fps at
most, so 59.94 is not taken for 60. The file is read through the shared stream probe.
"""

from __future__ import annotations

from fractions import Fraction
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from .. import frame_render
from .project import exported_version, version_dir
from .render import LOUDNESS, PROFILES, measure_loudness

FPS_TOLERANCE = 0.01


def _stderr(ffmpeg: str, args: list[str]) -> str:
    return subprocess.run([ffmpeg, "-hide_banner", "-nostats", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stderr


def _rate(value: Any) -> float:
    """A frame rate given as FFprobe's text ("60000/1001"), a number, or "" (0.0)."""

    try:
        return float(Fraction(str(value).strip())) if str(value or "").strip() else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def expected_from_report(report: dict[str, Any] | None) -> dict[str, Any]:
    """What a render report says its file must be: ``{"width", "height", "fps"}`` (fps as FFmpeg's
    exact text); {} for a report from before 226, which said nothing about it."""

    found = (report or {}).get("output_format")
    if not isinstance(found, dict):
        return {}
    return {key: found[key] for key in ("width", "height", "fps") if found.get(key)}


def _read_report(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return report if isinstance(report, dict) else {}


def _same_file(one: Any, other: Path) -> bool:
    try:
        return bool(str(one or "")) and os.path.samefile(str(one), str(other))
    except (OSError, ValueError):
        return False


def report_beside(path: Path, profile: str) -> dict[str, Any]:
    """The render report that describes this file; {} when there is none.

    226: a render report beside the file (``render-<profile>.json`` first, then any other
    ``render-*.json``, such as a validation run's) whose render is this very file (``os.path.samefile``),
    so the readable name, a hard link to the render, finds it too. A file in a project's ``export/`` is
    found by the export name its version's entry keeps, and that version's ``render-final.json`` is used:
    an export is a final, and it may be a copy when the drive cannot link.
    """

    path = Path(path)
    folder = path.parent
    beside = [folder / f"render-{profile}.json"] + sorted(p for p in folder.glob("render-*.json")
                                                          if p.name != f"render-{profile}.json")
    for candidate in beside:
        report = _read_report(candidate)
        if report and _same_file(report.get("output"), path):
            return report
    if folder.name == "export" and (folder.parent / "project.json").is_file():
        version = exported_version(folder.parent, path.name)
        if version is not None:
            return _read_report(version_dir(folder.parent, version) / "renders" / "render-final.json")
    return {}


def check_video(path: Path, profile: str, *, expected_duration: float | None = None,
                ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
                expected: dict[str, Any] | None = None) -> dict[str, Any]:
    """Check one rendered file. ``expected`` gives the frame size and rate it must have (226: from
    its render report, ``expected_from_report``); anything it leaves out is the profile's."""

    info = frame_render.probe_streams(ffprobe, Path(path))
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    if video is None or audio is None:
        check("has video and audio", False, "video or audio stream missing")
        return {"file": str(path), "passed": False, "checks": checks}
    given = {key: value for key, value in (expected or {}).items() if value}
    want = {"width": int(given.get("width") or PROFILES[profile]["width"]),
            "height": int(given.get("height") or PROFILES[profile]["height"]),
            "fps": str(given.get("fps") or PROFILES[profile]["fps"])}
    fps, want_fps = _rate(video.get("avg_frame_rate")), _rate(want["fps"])
    v_len, a_len = float(video.get("duration", 0)), float(audio.get("duration", 0))
    check("video format", video["codec_name"] == "h264" and video.get("pix_fmt") == "yuv420p",
          f"{video['codec_name']} {video.get('profile')} {video.get('pix_fmt')}")
    size_ok = (video["width"], video["height"]) == (want["width"], want["height"])
    check("frame size", size_ok,
          f"{video['width']}x{video['height']}" + ("" if size_ok else f", expected {want['width']}x{want['height']}"))
    rate_ok = abs(fps - want_fps) <= FPS_TOLERANCE
    check("frame rate", rate_ok, f"{fps:.3f} fps" + ("" if rate_ok else f", expected {want_fps:.3f} fps"))
    check("audio format", audio["codec_name"] == "aac" and int(audio["sample_rate"]) == 48000
          and int(audio["channels"]) == 2, f"{audio['codec_name']} {audio['sample_rate']} Hz {audio['channels']} ch")
    check("video and audio the same length", abs(v_len - a_len) < 0.15, f"video {v_len:.2f} s, audio {a_len:.2f} s")
    if expected_duration is not None:
        check("length matches the timeline", abs(v_len - expected_duration) < 0.5,
              f"{v_len:.2f} s, timeline {expected_duration:.2f} s")

    decode = _stderr(ffmpeg, ["-v", "error", "-i", str(path), "-f", "null", "-"])
    check("full decode without errors", not decode.strip(), decode.strip()[:300] or "clean")

    integrated, true_peak = measure_loudness(ffmpeg, path)
    check(f"loudness about {LOUDNESS['I']:.0f} LUFS", integrated is not None and abs(integrated - LOUDNESS["I"]) <= 1.0,
          f"{integrated} LUFS")
    check("true peak at or below -1 dBTP", true_peak is not None and true_peak <= -0.9, f"{true_peak} dBTP")

    black = _stderr(ffmpeg, ["-i", str(path), "-vf", "blackdetect=d=1.0:pix_th=0.10", "-an", "-f", "null", "-"])
    blacks = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", black)
    check("no black stretch over 1 s", not blacks,
          ", ".join(f"{float(s):.1f}-{float(e):.1f} s" for s, e in blacks) or "none")

    silence = _stderr(ffmpeg, ["-i", str(path), "-vn", "-af", "silencedetect=n=-50dB:d=1.5", "-f", "null", "-"])
    silences = re.findall(r"silence_start: ([\d.]+)", silence)
    check("no dead air over 1.5 s", not silences, ", ".join(f"{float(s):.1f} s" for s in silences) or "none")

    freeze = _stderr(ffmpeg, ["-i", str(path), "-vf", "freezedetect=n=0.001:d=3", "-an", "-f", "null", "-"])
    freezes = re.findall(r"freeze_start: ([\d.]+)", freeze)
    report = {
        "file": str(path),
        "profile": profile,
        "duration": round(v_len, 2),
        "passed": all(c["pass"] for c in checks),
        "checks": checks,
        "still_pictures_over_3s": [round(float(s), 1) for s in freezes],
        # 226: what the frame size and rate were checked against: given (by the render report or the
        # request), or the profile's.
        "expected": {**want, "from": "given" if given else "profile"},
    }
    return report
