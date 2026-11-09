from __future__ import annotations

from pathlib import Path
import unittest


class PromptTimeoutPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.scripts = {
            "Video Mangler.ps1": (cls.repo_root / "Video Mangler.ps1").read_text(encoding="utf-8"),
            "Audio Mangler.ps1": (cls.repo_root / "Audio Mangler.ps1").read_text(encoding="utf-8"),
        }

    def test_local_whisper_runtime_warning_uses_timed_continue_default(self) -> None:
        for script_name, script_text in self.scripts.items():
            with self.subTest(script=script_name):
                warning_function = self._function_body(script_text, "Get-InteractiveLocalWhisperLongRunDecision")
                self.assertIn("Local Whisper runtime warning", warning_function)
                self.assertIn("Read-TimedChoicePrompt", warning_function)
                self.assertIn('-DefaultValue "continue"', warning_function)
                self.assertIn("Auto-continues with {1}/default in {2}s", warning_function)
                self.assertIn('$choice.Trim().ToUpperInvariant() -eq "CONTINUE"', warning_function)
                self.assertNotIn("Read-Host", warning_function)

    def test_local_whisper_runtime_warning_choices_are_preserved(self) -> None:
        for script_name, script_text in self.scripts.items():
            with self.subTest(script=script_name):
                warning_function = self._function_body(script_text, "Get-InteractiveLocalWhisperLongRunDecision")
                self.assertIn('Action    = "continue"', warning_function)
                self.assertIn('Action    = "switch_model"', warning_function)
                self.assertIn('ModelName = "small"', warning_function)
                self.assertIn('Action    = "cancel"', warning_function)
                self.assertIn('"S" {', warning_function)
                self.assertIn('"X" {', warning_function)

    def test_prompt_timeout_zero_is_the_only_raw_default_prompt_escape(self) -> None:
        for script_name, script_text in self.scripts.items():
            with self.subTest(script=script_name):
                timed_prompt = self._function_body(script_text, "Read-TimedDefaultPrompt")
                self.assertIn("if ($TimeoutSeconds -le 0)", timed_prompt)
                self.assertIn("return (Read-Host $Prompt)", timed_prompt)
                self.assertEqual(timed_prompt.count("Read-Host $Prompt"), 1)
                self.assertIn("Prompt skipped by -NoPrompt; using default", timed_prompt)
                self.assertIn("Prompt timed out after {0}s; using default: {1}", timed_prompt)
                self.assertIn("Prompt could not poll console for timed input; using default", timed_prompt)
                self.assertIn("Prompt timed input failed before completion; using default", timed_prompt)

    def test_no_prompt_skips_local_whisper_runtime_warning_path(self) -> None:
        for script_name, script_text in self.scripts.items():
            with self.subTest(script=script_name):
                transcript_function = self._function_body(script_text, "Invoke-PythonWhisperTranscript")
                guard = "-not $InteractiveMode -or -not $AllowInteractiveLongRunPrompt -or -not $heuristicPlan.LongRunPromptRecommended"
                self.assertIn(guard, transcript_function)
                self.assertIn("Get-InteractiveLocalWhisperLongRunDecision", transcript_function)

    def test_raw_read_host_is_only_used_for_explicitly_allowlisted_blocking_input(self) -> None:
        allowlist = {
            "Video Mangler.ps1": [
                'Read-Host ("Enter {0} folder path"',
                "return (Read-Host $Prompt)",
                "$remoteInput = Read-Host $prompt",
                'Read-Host "Paste the OpenAI API key for this run only"',
                'Read-Host "Type 1, 2, 3, 4, or 5"',
                'Read-Host "Type 1, 2, 3, or 4"',
                'Read-Host "Type 1, 2, or 3"',
                'Read-Host "Type I to install now, S to skip this translation, or C to cancel"',
                'Read-Host "Search archive catalog. Enter terms"',
            ],
            "Audio Mangler.ps1": [
                'Read-Host ("Enter {0} folder path"',
                "return (Read-Host $Prompt)",
                "$remoteInput = Read-Host $prompt",
                'Read-Host "Paste a full local file or folder path"',
                'Read-Host "Paste the OpenAI API key for this run only"',
                'Read-Host "Type 1, 2, 3, 4, or 5"',
                'Read-Host "Type 1, 2, 3, or 4"',
                'Read-Host "Type 1, 2, or 3"',
                'Read-Host "Type I to install now, S to skip this translation, or C to cancel"',
            ],
        }

        for script_name, script_text in self.scripts.items():
            with self.subTest(script=script_name):
                violations: list[str] = []
                for line_number, line in enumerate(script_text.splitlines(), start=1):
                    if "Read-Host" not in line:
                        continue
                    if any(allowed in line for allowed in allowlist[script_name]):
                        continue
                    violations.append(f"{line_number}: {line.strip()}")

                self.assertEqual(violations, [])

    def test_video_safe_default_prompts_are_timed(self) -> None:
        video_text = self.scripts["Video Mangler.ps1"]
        expected_timed_prompts = [
            "Create this folder now? (Y/n, auto-selects Y",
            "Press Enter to use these folders, or type another base folder. Auto-selects",
            "Continue with this expanded run? (y/N, auto-selects N",
            "Press Enter to choose a local file or folder instead, or type Q to stop. Auto-selects local input",
            "Search terms (press Enter to skip; auto-skips",
            "Press Enter for Track 1; auto-selects Track 1",
            "Press Enter to use that folder, or type a different full output folder path. Auto-selects",
            "Press Enter to use that catalog path, or type a different full catalog folder path. Auto-selects",
            "Optional manual notes CSV to import now (press Enter to skip; auto-skips",
            "Target repo hint for this evidence package? Press Enter to auto-detect",
        ]
        for prompt in expected_timed_prompts:
            with self.subTest(prompt=prompt):
                self.assertIn(prompt, video_text)

    def test_destructive_or_expanded_prompts_default_to_no(self) -> None:
        for script_name, script_text in self.scripts.items():
            with self.subTest(script=script_name):
                expanded_function = self._function_body(script_text, "Confirm-ExpandedRunScope")
                self.assertIn("Continue with this expanded run? (y/N, auto-selects N", expanded_function)
                self.assertIn("-DefaultYes:$false", expanded_function)

        video_text = self.scripts["Video Mangler.ps1"]
        self.assertIn("Overwrite existing transcript/audio files? (y/N, auto-selects N", video_text)
        self.assertIn("-DefaultYes $false", video_text)

    def _function_body(self, script_text: str, function_name: str) -> str:
        marker = f"function {function_name} "
        start = script_text.find(marker)
        if start < 0:
            self.fail(f"Could not find function {function_name}")
        next_function = script_text.find("\nfunction ", start + len(marker))
        if next_function < 0:
            return script_text[start:]
        return script_text[start:next_function]


if __name__ == "__main__":
    unittest.main()
