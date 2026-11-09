from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _invoke_provider(script_name: str, *, detected_language: str, target_language: str) -> dict[str, str]:
    script_path = REPO_ROOT / script_name
    ps_source = textwrap.dedent(
        f"""
        $ErrorActionPreference = 'Stop'
        $scriptPath = '{script_path}'
        $parseErrors = $null
        $tokens = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$parseErrors)
        if ($parseErrors -and $parseErrors.Count -gt 0) {{
            throw ('Failed to parse ' + $scriptPath)
        }}

        $wantedNames = @('Get-PrimaryLanguageTag', 'Get-CanonicalLanguageCode', 'Resolve-TranslationTargetProvider')
        $functionTexts = @(
            $ast.FindAll({{
                param($node)
                $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $wantedNames -contains $node.Name
            }}, $true) |
            Sort-Object {{ $_.Extent.StartOffset }} |
            ForEach-Object {{ $_.Extent.Text }}
        )

        foreach ($functionText in $functionTexts) {{
            Invoke-Expression $functionText
        }}

        function Test-OpenAiTranslationAvailable {{ return $true }}
        function Ensure-ArgosTranslationSupport {{ return 'ready' }}

        $result = Resolve-TranslationTargetProvider `
            -TranslationMode 'OpenAI' `
            -TargetLanguage '{target_language}' `
            -DetectedLanguage '{detected_language}' `
            -ModelName 'medium' `
            -PythonCommand 'python' `
            -InteractiveMode:$false `
            -HeartbeatSeconds 10

        $result | ConvertTo-Json -Compress
        """
    ).strip()

    with tempfile.TemporaryDirectory() as temp_dir:
        harness_path = Path(temp_dir) / "provider-harness.ps1"
        harness_path.write_text(ps_source, encoding="utf-8")
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(harness_path),
            ],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    return json.loads(completed.stdout.strip())


class TranslationProviderTests(unittest.TestCase):
    def test_audio_translation_provider_skips_english_to_english_openai_text_translation(self) -> None:
        result = _invoke_provider(
            "Audio Mangler.ps1",
            detected_language="english",
            target_language="en",
        )

        self.assertEqual(result["Action"], "ready")
        self.assertEqual(result["Provider"], "Original transcript copy")

    def test_video_translation_provider_skips_english_to_english_openai_text_translation(self) -> None:
        result = _invoke_provider(
            "Video Mangler.ps1",
            detected_language="english",
            target_language="en",
        )

        self.assertEqual(result["Action"], "ready")
        self.assertEqual(result["Provider"], "Original transcript copy")


if __name__ == "__main__":
    unittest.main()
