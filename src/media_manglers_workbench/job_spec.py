"""JobSpec v1 for the Video Mangler Workbench."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


WORKFLOW_CODEX_EVIDENCE_PACKAGE = "codex-evidence-package"


def _first(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return default


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(slots=True)
class JobSpec:
    """Serializable operator job definition for the first workbench workflow."""

    schema_version: int = 1
    workflow: str = WORKFLOW_CODEX_EVIDENCE_PACKAGE
    input_path: str = ""
    output_folder: str = ""
    repo_root: str = ""
    script_path: str = ".\\Video Mangler.ps1"
    whisper_model: str = "medium"
    language: str = "en"
    narration_speech_mode: str = "Sparse"
    pre_context_seconds: float = 120
    post_context_seconds: float = 240
    evidence_frame_cadence_seconds: float = 15
    evidence_max_frames_per_candidate: int = 24
    evidence_render_density: str = "Compact"
    evidence_profile_setup_name: str = "iRacing Ticket Evidence - Balanced"
    evidence_panel_crops: str = "Auto"
    evidence_repo_hint_mode: str = "auto"
    evidence_target_repo: str = ""
    evidence_repo_map_path: str = ""
    no_prompt: bool = True
    extra_args: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(f"Unsupported JobSpec schemaVersion: {self.schema_version}")
        if self.workflow != WORKFLOW_CODEX_EVIDENCE_PACKAGE:
            raise ValueError(f"Unsupported workbench workflow: {self.workflow}")
        if not self.input_path:
            raise ValueError("inputPath is required.")
        if not self.output_folder:
            raise ValueError("outputFolder is required.")

    def resolved_script_path(self) -> str:
        script = Path(self.script_path)
        if script.is_absolute() or not self.repo_root:
            return str(script)
        return str(Path(self.repo_root) / script)

    def evidence_package_dir(self) -> Path:
        return Path(self.output_folder) / "codex-evidence-package"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "workflow": self.workflow,
            "inputPath": self.input_path,
            "outputFolder": self.output_folder,
            "repoRoot": self.repo_root,
            "scriptPath": self.script_path,
            "whisperModel": self.whisper_model,
            "language": self.language,
            "narrationSpeechMode": self.narration_speech_mode,
            "preContextSeconds": self.pre_context_seconds,
            "postContextSeconds": self.post_context_seconds,
            "evidenceFrameCadenceSeconds": self.evidence_frame_cadence_seconds,
            "evidenceMaxFramesPerCandidate": self.evidence_max_frames_per_candidate,
            "evidenceRenderDensity": self.evidence_render_density,
            "evidenceProfileSetupName": self.evidence_profile_setup_name,
            "evidencePanelCrops": self.evidence_panel_crops,
            "evidenceRepoHintMode": self.evidence_repo_hint_mode,
            "evidenceTargetRepo": self.evidence_target_repo,
            "evidenceRepoMapPath": self.evidence_repo_map_path,
            "noPrompt": self.no_prompt,
            "extraArgs": list(self.extra_args),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "JobSpec":
        extra_args = _first(payload, "extraArgs", "extra_args", default=[])
        if isinstance(extra_args, str):
            extra_args = [extra_args]
        elif not isinstance(extra_args, list):
            extra_args = []
        return cls(
            schema_version=_as_int(_first(payload, "schemaVersion", "schema_version", default=1), 1),
            workflow=str(_first(payload, "workflow", default=WORKFLOW_CODEX_EVIDENCE_PACKAGE)),
            input_path=str(_first(payload, "inputPath", "input_path", default="")),
            output_folder=str(_first(payload, "outputFolder", "output_folder", default="")),
            repo_root=str(_first(payload, "repoRoot", "repo_root", default="")),
            script_path=str(_first(payload, "scriptPath", "script_path", default=".\\Video Mangler.ps1")),
            whisper_model=str(_first(payload, "whisperModel", "whisper_model", default="medium")),
            language=str(_first(payload, "language", default="en")),
            narration_speech_mode=str(
                _first(payload, "narrationSpeechMode", "narration_speech_mode", default="Sparse")
            ),
            pre_context_seconds=_as_float(_first(payload, "preContextSeconds", "pre_context_seconds", default=120), 120),
            post_context_seconds=_as_float(_first(payload, "postContextSeconds", "post_context_seconds", default=240), 240),
            evidence_frame_cadence_seconds=_as_float(
                _first(payload, "evidenceFrameCadenceSeconds", "evidence_frame_cadence_seconds", default=15),
                15,
            ),
            evidence_max_frames_per_candidate=_as_int(
                _first(payload, "evidenceMaxFramesPerCandidate", "evidence_max_frames_per_candidate", default=24),
                24,
            ),
            evidence_render_density=str(
                _first(payload, "evidenceRenderDensity", "evidence_render_density", default="Compact")
            ),
            evidence_profile_setup_name=str(
                _first(
                    payload,
                    "evidenceProfileSetupName",
                    "evidence_profile_setup_name",
                    default="iRacing Ticket Evidence - Balanced",
                )
            ),
            evidence_panel_crops=str(_first(payload, "evidencePanelCrops", "evidence_panel_crops", default="Auto")),
            evidence_repo_hint_mode=str(
                _first(payload, "evidenceRepoHintMode", "evidence_repo_hint_mode", default="auto")
            ),
            evidence_target_repo=str(_first(payload, "evidenceTargetRepo", "evidence_target_repo", default="")),
            evidence_repo_map_path=str(_first(payload, "evidenceRepoMapPath", "evidence_repo_map_path", default="")),
            no_prompt=_as_bool(_first(payload, "noPrompt", "no_prompt", default=True), True),
            extra_args=[str(item) for item in extra_args],
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n"

    @classmethod
    def from_json(cls, payload: str) -> "JobSpec":
        return cls.from_dict(json.loads(payload))
