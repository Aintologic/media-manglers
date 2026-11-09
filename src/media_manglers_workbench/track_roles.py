"""The per-track narration setting on the Settings page (196).

For a recording whose audio tracks have no names, each of Tracks 1-6 is Auto, Narration, Never
narration, Game audio or Full mix. Recordings with track names use the names instead
(``voice_track.role_from_name``). The setting is kept as one text value, "2=narration,3=game"
(track number = role, Auto left out), which the backend reads as ``-EvidenceTrackRoles``. Every
track Auto is the empty text, so a new user gets plain detection.

"Game audio" (220) is a kind of Never narration: the narration choice treats it exactly as Never
narration, and the activity timeline listens to it for idle time. "Full mix" (220) is what a track
named "Full Mix" is: narration only when no other track qualifies, and what idle time is estimated from
when the game-audio track is missing or silent.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QFormLayout, QLabel, QWidget

from .metadata import METADATA_BY_KEY
from .widgets import WheelSafeComboBox

SETTING_KEY = "evidence_track_roles"
TRACK_COUNT = 6
ROLE_CHOICES: tuple[tuple[str, str], ...] = (
    ("auto", "Auto"),
    ("narration", "Narration"),
    ("never", "Never narration"),
    ("game", "Game audio"),
    ("full_mix", "Full mix"),
)
_KEPT_ROLES = ("narration", "never", "game", "full_mix")


def parse_roles(text: Any) -> dict[int, str]:
    """"2=narration,3=game" -> {2: "narration", 3: "game"}; Auto and anything unreadable left out."""

    roles: dict[int, str] = {}
    for part in str(text or "").replace(";", ",").split(","):
        number, _, role = part.partition("=")
        role = role.strip().casefold()
        if number.strip().isdigit() and int(number) >= 1 and role in _KEPT_ROLES:
            roles[int(number)] = role
    return roles


def format_roles(roles: dict[int, str]) -> str:
    return ",".join(f"{number}={role}" for number, role in sorted(roles.items()) if role in _KEPT_ROLES)


class TrackRolesPanel(QWidget):
    """Six choices, one row per track with its label on the left. Owns no settings itself.

    One row each: side by side, a choice read as belonging to the next track's label (196).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        tooltip = METADATA_BY_KEY[SETTING_KEY].tooltip
        self.combos: dict[int, WheelSafeComboBox] = {}
        for number in range(1, TRACK_COUNT + 1):
            combo = WheelSafeComboBox()
            combo.setObjectName(f"trackRoleCombo{number}")
            for value, text in ROLE_CHOICES:
                combo.addItem(text, value)
            combo.setToolTip(tooltip)
            self.combos[number] = combo
            label = QLabel(f"Track {number}:")
            label.setBuddy(combo)
            form.addRow(label, combo)
        self.setToolTip(tooltip)

    def load(self, settings: dict[str, Any]) -> None:
        roles = parse_roles(settings.get(SETTING_KEY))
        for number, combo in self.combos.items():
            combo.setCurrentIndex(max(0, combo.findData(roles.get(number, "auto"))))

    def values(self) -> dict[str, Any]:
        roles = {number: str(combo.currentData() or "auto") for number, combo in self.combos.items()}
        return {SETTING_KEY: format_roles(roles)}
