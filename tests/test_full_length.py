"""Regressions for the full-length rebuild plan.

The rebuild places the measured copy window over the missing opening, so the
placement has to be arithmetic on numbers the map already produced — never a
guess about where the copied footage came from. A rebuild that quietly shows
made-up or misaligned material would break the project's one hard rule.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "forensics"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import nvidia_fix  # noqa: E402

REAL_MAP = ROOT / "recovery" / "duplication_dense.json"


def verdict(first=(0.12, 200.0), last=(50.0, 260.0), damaged=60.0):
    return nvidia_fix.DuplicationVerdict(
        damaged_seconds=damaged,
        duplicated_seconds=0.0,
        destroyed_seconds=0.0,
        scan_blocks=1,
        matched_blocks=1,
        first_match=first,
        last_match=last,
    )


class PlanArithmeticTests(unittest.TestCase):
    def test_copy_window_fills_the_missing_opening(self):
        # 114.03 s missing, and the copy window sits 180..300 s in the source.
        plan = nvidia_fix.plan_full_length(
            114.031811, 185.981, verdict((0.12, 180.0), (50.0, 300.0)),
        )
        self.assertAlmostEqual(plan.duration, 114.031811)
        self.assertAlmostEqual(plan.start_in_tail, 180.0 - 114.031811)
        self.assertAlmostEqual(plan.shortfall, 0.0)
        self.assertLessEqual(plan.start_in_tail + plan.duration, 185.981)

    def test_short_copy_window_reports_the_shortfall(self):
        plan = nvidia_fix.plan_full_length(
            114.0, 185.0, verdict((0.12, 200.0), (50.0, 260.0)),
        )
        self.assertAlmostEqual(plan.duration, 60.0)
        self.assertAlmostEqual(plan.available, 60.0)
        self.assertAlmostEqual(plan.shortfall, 54.0)

    def test_copy_starting_before_the_cut_clamps_to_zero(self):
        plan = nvidia_fix.plan_full_length(
            114.0, 185.0, verdict((0.12, 100.0), (50.0, 300.0)),
        )
        self.assertEqual(plan.start_in_tail, 0.0)
        self.assertEqual(plan.timeline_start, 114.0)

    def test_copy_running_past_the_tail_end_is_pulled_back(self):
        plan = nvidia_fix.plan_full_length(
            114.0, 60.0, verdict((0.12, 200.0), (50.0, 400.0)),
        )
        self.assertAlmostEqual(plan.duration, 60.0)
        self.assertLessEqual(plan.start_in_tail + plan.duration, 60.0)

    def test_no_plan_without_a_map_or_matches(self):
        self.assertIsNone(nvidia_fix.plan_full_length(114.0, 186.0, None))
        empty = nvidia_fix.DuplicationVerdict(114.0, 0.0, 114.0, 1, 0, None, None)
        self.assertIsNone(nvidia_fix.plan_full_length(114.0, 186.0, empty))

    def test_no_plan_for_a_negligible_opening(self):
        self.assertIsNone(
            nvidia_fix.plan_full_length(0.2, 186.0, verdict())
        )

    def test_plan_dict_is_rounded(self):
        plan = nvidia_fix.plan_full_length(114.0, 185.0, verdict())
        doc = plan.to_dict()
        self.assertEqual(doc["filled_seconds"], 60.0)
        self.assertIsInstance(doc["start_in_tail_seconds"], float)


class RecordedMapTests(unittest.TestCase):
    """The real recording's map must reproduce the numbers already published."""

    def setUp(self):
        if not REAL_MAP.is_file():
            self.skipTest("recovery/duplication_dense.json is not present")

    def test_plan_matches_the_shipped_full_length_build(self):
        payload = json.loads(REAL_MAP.read_text(encoding="utf-8"))
        found = nvidia_fix.duplication_verdict(payload["rows"], 113.781922)
        plan = nvidia_fix.plan_full_length(114.031811, 185.981, found)

        self.assertAlmostEqual(plan.start_in_tail, 68.508, places=3)
        self.assertAlmostEqual(plan.duration, 114.031811, places=6)
        self.assertAlmostEqual(plan.shortfall, 0.0)
        self.assertAlmostEqual(plan.timeline_start, 182.54, places=2)
        self.assertAlmostEqual(
            114.031811 + 185.981, 300.012811, places=6
        )


class ConcatEntryTests(unittest.TestCase):
    def test_windows_paths_become_demuxer_safe(self):
        entry = nvidia_fix._concat_entry(Path(r"D:\a b\c'd.mp4"))
        self.assertEqual(entry, "file 'D:/a b/c'\\''d.mp4'")


if __name__ == "__main__":
    unittest.main()
