"""Privacy masks for the operator's cameras (150).

A mask is a greyscale image the size of one camera panel; white is private. Masks belong to the
operator: they are stored in per-user application data, never in the repository or beside a
recording. They are applied to every render (see ``render.py``) and to every still and contact
sheet prepared for an AI editor, before the AI can see it.

226 (decision F): only the operator draws a mask, in the Workbench's mask editor. A request from the
AI editor always gets the stored masks (it may add one, never remove one), and a layout that would
move a masked camera, leave it out, or show it through another panel, is refused (``layout_problem``);
the render blurs a panel over a masked camera even so (``render.py``). These guards stop mistakes,
not a determined agent: an agent with access to the files could still edit them by hand.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Iterable

from ..user_folders import settings_root


def default_store() -> Path:
    root = os.environ.get("MEDIA_MANGLERS_RACE_VIDEO_PRIVACY") or ""
    if root:
        return Path(root)
    return settings_root() / "MediaManglers" / "race-video" / "privacy"


def load_masks(store: Path | None = None) -> dict[str, Path]:
    """The operator's masks, by panel name. Missing files are left out."""

    store = store or default_store()
    index = store / "masks.json"
    if not index.exists():
        return {}
    data = json.loads(index.read_text(encoding="utf-8"))
    masks = {}
    for panel, name in (data.get("masks") or {}).items():
        path = store / name
        if path.is_file():
            masks[str(panel)] = path
    return masks


def save_mask(panel: str, image: Path, store: Path | None = None) -> Path:
    """Copy ``image`` into the store as the mask for ``panel``."""

    store = store or default_store()
    store.mkdir(parents=True, exist_ok=True)
    target = store / f"{panel}.png"
    shutil.copyfile(image, target)
    index = store / "masks.json"
    data: dict[str, Any] = json.loads(index.read_text(encoding="utf-8")) if index.exists() else {}
    data.setdefault("masks", {})[panel] = target.name
    temp = index.with_name(".masks.json.tmp")
    temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(temp, index)
    return target


def overlaps(first: Iterable[Any], second: Iterable[Any]) -> bool:
    """True when two [x, y, w, h] rectangles share any pixel (touching edges do not)."""

    ax, ay, aw, ah = (int(value) for value in first)
    bx, by, bw, bh = (int(value) for value in second)
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def layout_problem(layout: Any, fixed: dict[str, Any], panels: Iterable[str]) -> str:
    """Why ``layout`` would move a privacy mask or miss it (226, decision F), or "" when it would not.

    A mask covers its panel's rectangle in ``fixed``, the layout the project was prepared with.
    ``layout`` (a request's, or a timeline's ``source_layout``) must keep the frame size and the
    rectangle of each of ``panels`` (the panels with a stored mask) that ``fixed`` has; otherwise the
    blur would land in the wrong place, or nowhere. Other panels may differ, but a panel without a
    mask of its own may not cover any part of a masked camera's rectangle: a second name for that
    camera, or a wide panel over it, would show it through no mask at all.
    """

    fixed_panels = dict((fixed or {}).get("panels") or {})
    masks = {str(panel) for panel in panels}
    masked = sorted(masks & set(fixed_panels))
    if not masked:
        return ""
    try:
        size = (int(layout["width"]), int(layout["height"]))
        rectangles = {str(name): [int(value) for value in box] for name, box in dict(layout["panels"]).items()}
    except (KeyError, TypeError, ValueError):
        return "it does not give the width, height and panels"
    if any(len(box) != 4 for box in rectangles.values()):
        return "it does not give the width, height and panels"
    if size != (int(fixed["width"]), int(fixed["height"])):
        return f"it is {size[0]}x{size[1]}, not {int(fixed['width'])}x{int(fixed['height'])}"
    for panel in masked:
        if panel not in rectangles:
            return f"it leaves out the {panel} camera, which has a privacy mask"
        if rectangles[panel] != [int(value) for value in fixed_panels[panel]]:
            return f"it moves the {panel} camera, which has a privacy mask"
    for name, box in sorted(rectangles.items()):
        if name in masks:
            continue
        for panel in masked:
            if overlaps(box, fixed_panels[panel]):
                return f"its {name} panel covers the {panel} camera, which has a privacy mask"
    return ""


def fingerprint(masks: dict[str, Path]) -> dict[str, str]:
    """What each mask covers, by its contents: a mask redrawn under the same name is a different mask."""

    return {panel: hashlib.sha256(Path(path).read_bytes()).hexdigest() for panel, path in sorted(masks.items())}


def build_full_frame_mask(ffmpeg: str, layout: dict[str, Any], masks: dict[str, Path], out: Path,
                          width: int, height: int) -> Path | None:
    """One mask for the whole recording frame, scaled to ``width`` x ``height``; None when no mask applies."""

    used = {panel: path for panel, path in masks.items() if panel in layout["panels"]}
    if not used:
        return None
    sx, sy = width / layout["width"], height / layout["height"]
    inputs = ["-f", "lavfi", "-i", f"color=black:s={width}x{height}"]
    parts, current = [], "0:v"
    for index, (panel, path) in enumerate(sorted(used.items()), start=1):
        x, y, w, h = (int(v) for v in layout["panels"][panel])
        inputs += ["-i", str(path)]
        pw, ph, px, py = max(1, round(w * sx)), max(1, round(h * sy)), round(x * sx), round(y * sy)
        parts.append(f"[{index}:v]scale={pw}:{ph},format=gray[m{index}]")
        parts.append(f"[{current}][m{index}]overlay={px}:{py}[o{index}]")
        current = f"o{index}"
    parts.append(f"[{current}]format=gray[out]")
    out.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([ffmpeg, "-hide_banner", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(parts),
                             "-map", "[out]", "-frames:v", "1", str(out)], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"could not build the privacy mask: {result.stderr.strip()[-500:]}")
    return out
