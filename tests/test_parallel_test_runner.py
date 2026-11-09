"""The parallel test runner shares the tests out fairly and runs each exactly once (167)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

RUNNER = Path(__file__).resolve().parents[1] / "tools" / "validation" / "run_tests_parallel.py"
spec = importlib.util.spec_from_file_location("run_tests_parallel", RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class PlanBucketsTests(unittest.TestCase):
    def test_every_test_runs_exactly_once_and_the_load_is_even(self) -> None:
        big = [f"tests/test_gui.py::GuiTests::test_{n}" for n in range(300)]
        small = [f"tests/test_{f}.py::Case::test_{n}" for f in "abcdefghij" for n in range(12)]
        loose = [f"tests/test_loose.py::test_{n}" for n in range(5)]
        nodes = big + small + loose
        buckets = runner.plan_buckets(nodes, 6)
        flat = [node for bucket in buckets for node in bucket]
        self.assertEqual(sorted(flat), sorted(nodes), "each test once, none lost")
        sizes = [len(bucket) for bucket in buckets]
        self.assertLessEqual(max(sizes) - min(sizes), 50, sizes)
        self.assertEqual(sum(1 for bucket in buckets if any("test_gui.py" in n for n in bucket)), 6,
                         "a long class is cut into slices so it does not hold up one process")

    def test_a_small_class_stays_in_one_process(self) -> None:
        nodes = [f"tests/test_a.py::Case::test_{n}" for n in range(10)] + ["tests/test_b.py::test_one"]
        buckets = runner.plan_buckets(nodes, 4)
        holders = [bucket for bucket in buckets if any("test_a.py" in n for n in bucket)]
        self.assertEqual(len(holders), 1, "its set-up runs once")

    def test_group_key(self) -> None:
        self.assertEqual(runner.group_key("tests/test_a.py::Case::test_x"), "tests/test_a.py::Case")
        self.assertEqual(runner.group_key("tests/test_a.py::test_x"), "tests/test_a.py")
        self.assertEqual(runner.group_key("tests/test_a.py::Case::test_x[sub]"), "tests/test_a.py::Case")


if __name__ == "__main__":
    unittest.main()
