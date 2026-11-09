"""``tests/script_functions.function_text`` must end each function where PowerShell's parser does (224)."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import textwrap
import unittest

from tests.script_functions import function_text

SCRIPT = Path(__file__).resolve().parents[1] / "Video Mangler.ps1"


class FunctionTextTests(unittest.TestCase):
    def test_every_top_level_function_ends_where_the_parser_says(self) -> None:
        source = textwrap.dedent(
            f"""
            $tokens = $null; $parseErrors = $null
            $ast = [System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$tokens, [ref]$parseErrors)
            $top = $ast.FindAll({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Parent.Parent -eq $ast }}, $false)
            @($top | ForEach-Object {{ [pscustomobject]@{{ name = $_.Name; first = $_.Extent.StartLineNumber; last = $_.Extent.EndLineNumber }} }}) | ConvertTo-Json -Compress
            """
        ).strip()
        run = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", source],
                             capture_output=True, text=True, timeout=300)
        parsed = [(item["name"], item["first"], item["last"]) for item in json.loads(run.stdout)]
        self.assertGreater(len(parsed), 300)
        text = SCRIPT.read_text(encoding="utf-8-sig")
        found = []
        for name, _first, _last in parsed:
            first = text[:text.index(f"function {name} {{")].count("\n") + 1
            found.append((name, first, first + function_text(text, name).count("\n")))
        self.assertEqual(found, parsed)

    def test_the_last_function_in_the_script_stops_before_the_main_body(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8-sig")
        body = function_text(text, "Invoke-CodexEvidencePackageBatch")
        self.assertTrue(body.endswith("\n}"), body[-200:])
        self.assertNotIn("\nfunction ", body)
        self.assertTrue(text[text.index(body) + len(body):].strip(), "the main body should follow it")


if __name__ == "__main__":
    unittest.main()
