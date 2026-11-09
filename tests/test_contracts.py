from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from media_manglers.contracts import CommandEnvelope, CommandResult, read_json_file, write_json_file


class ContractsTests(unittest.TestCase):
    def test_command_envelope_round_trips(self) -> None:
        envelope = CommandEnvelope(payload={"mode": "Local", "targets": ["en"]})
        self.assertEqual(
            envelope.to_dict(),
            {"payload": {"mode": "Local", "targets": ["en"]}},
        )

    def test_command_result_round_trips_via_utf8_json(self) -> None:
        result = CommandResult(ok=True, data={"text": "Das heißt"}, error="")
        with tempfile.TemporaryDirectory() as temp_dir:
            path = f"{temp_dir}\\result.json"
            write_json_file(path, result.to_dict())
            loaded = read_json_file(path)

        self.assertEqual(loaded["ok"], True)
        self.assertEqual(loaded["data"]["text"], "Das heißt")
        self.assertEqual(loaded["error"], "")

    def test_read_json_file_accepts_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = f"{temp_dir}\\request.json"
            with open(path, "w", encoding="utf-8-sig") as handle:
                handle.write('{"payload":{"language":"de"}}')
            loaded = read_json_file(path)

        self.assertEqual(loaded["payload"]["language"], "de")


if __name__ == "__main__":
    unittest.main()
