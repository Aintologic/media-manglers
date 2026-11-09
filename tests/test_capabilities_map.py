"""220: governance/CAPABILITIES.md matches the code.

Every `path::name` the map names must still exist: the file, and a function, class, method or
assignment of that name in it. A rename or deletion fails here until the map is updated, which is
the rule in AGENTS.md: a wave is not done until the map matches the code.
"""

from __future__ import annotations

import ast
from pathlib import Path
import re
import unittest

REPO = Path(__file__).resolve().parents[1]
MAP = REPO / "governance" / "CAPABILITIES.md"
REFERENCE = re.compile(r"`([^`\s]+\.(?:py|ps1))::([A-Za-z_][A-Za-z0-9_]*)`")


def _names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.add(node.name)
        elif isinstance(node, ast.Assign):
            found.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            found.add(node.target.id)
    return found


class CapabilitiesMapTests(unittest.TestCase):
    def test_every_named_part_still_exists(self) -> None:
        text = MAP.read_text(encoding="utf-8")
        references = REFERENCE.findall(text)
        self.assertGreater(len(references), 60, "the map names the code it describes")
        missing = []
        cache: dict[str, set[str]] = {}
        for relative, name in references:
            path = REPO / relative
            if not path.is_file():
                missing.append(f"{relative} (no such file)")
                continue
            if path.suffix == ".py":
                names = cache.setdefault(relative, _names(path))
                if name not in names:
                    missing.append(f"{relative}::{name}")
            elif f"function {name}" not in path.read_text(encoding="utf-8-sig"):
                missing.append(f"{relative}::{name}")
        self.assertEqual(missing, [], "CAPABILITIES.md names code that no longer exists")

    def test_the_twelve_shared_parts_the_operator_named_are_on_the_map(self) -> None:
        text = MAP.read_text(encoding="utf-8").casefold()
        for part in ("player", "narration-track choice", "whisper loader", "word list", "filters",
                     "audio extractor", "frame renderer", "zip writer", "output-folder rule", "status rule",
                     "queue controls", "raw bin library"):
            with self.subTest(part=part):
                self.assertIn(part, text)

    # 226: the shared parts the AI Video Editor moved onto in Wave 7: (the row's first words, a part the
    # row names that the editor's own code uses).
    WAVE_7_EDITOR_ROWS = (
        ("Narration-track choice: track names and roles", "track_roles"),
        ("Narration-track choice: voice detection", "detect_voice_track"),
        ("Game-audio track", "game_audio_track"),
        ("Whisper loader", "whisper_transcriber"),
        ("Whisper settings rule", "from_settings"),
        ("Transcription with the invented-line filters", "transcribe_from_request"),
        ("Cross-track and near-silent filters", "is_silence_hallucination_text"),
        ("Cross-track check: cutting lines from audio already decoded", "wav_slice_extractor"),
        ("Short real reactions", "reanchor_short_reactions"),
        ("Audio extractor", "extract_all_tracks"),
        ("Frame renderer: stills, contact sheets", "render_stills"),
        ("Frame renderer: the game-picture sampler", "picture_output"),
        ("Video and audio-track probes", "probe_audio_streams"),
        ("Output-folder rule", "temporary_folder_problem"),
        ("Activity timeline (idle time)", "speech_stretches"),
        ("Activity timeline: signal 2", "combined_timeline"),
        ("Raw bin library", "idle_from_levels"),
    )

    def test_the_editors_wave_7_shared_parts_are_on_the_map_and_in_its_code(self) -> None:
        rows: dict[str, tuple[str, str]] = {}
        for line in MAP.read_text(encoding="utf-8").splitlines():
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if line.startswith("|") and len(cells) == 3:
                rows[cells[0]] = (cells[1], cells[2])
        editor = REPO / "src" / "media_manglers" / "core" / "race_video"
        used: set[str] = set()
        for path in editor.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Attribute):
                    used.add(node.attr)
                elif isinstance(node, ast.Name):
                    used.add(node.id)
                elif isinstance(node, ast.ImportFrom):
                    used.update(alias.name for alias in node.names)
        for start, part in self.WAVE_7_EDITOR_ROWS:
            with self.subTest(row=start):
                found = [name for name in rows if name.startswith(start)]
                self.assertEqual(len(found), 1, f"one row starts {start!r}")
                where, users = rows[found[0]]
                self.assertRegex(users, r"(^|\D)4(\D|$)", "the row lists feature 4 among its users")
                self.assertIn(f"::{part}`", where, "the row names the part")
                self.assertIn(part, used, "the editor's code uses it")

    def test_agents_md_holds_the_rule(self) -> None:
        agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("A wave is not done until `governance/CAPABILITIES.md` matches the code", agents)


if __name__ == "__main__":
    unittest.main()
