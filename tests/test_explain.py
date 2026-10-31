"""Regressions for the `explain` duplication verdict.

The verdict decides what the app tells the user about the 37.9% it cannot
recover, so the split between "copied later" and "destroyed" has to be
arithmetic, not narrative. These tests pin the arithmetic to synthesized maps
and to the recorded map of the real recording when it is present.
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


def rows(spec):
    """Build map rows from (t, matched) pairs; `src_t` only matters when matched."""
    return [
        {"t": t, "matched": matched, "src": 0 if matched else None,
         "src_t": t + 180.0 if matched else None, "run": 8192, "entropy": 5.0}
        for t, matched in spec
    ]


class DuplicationVerdictTests(unittest.TestCase):
    def test_prefix_splits_into_copied_and_destroyed(self):
        # 0-2 s copied, 2-3 s copied, 3-4 s garbage, 4-5 s copied => 4 s / 1 s.
        verdict = nvidia_fix.duplication_verdict(
            rows([(0.0, True), (2.0, True), (3.0, False), (4.0, True)]), 5.0
        )
        self.assertAlmostEqual(verdict.duplicated_seconds, 4.0)
        self.assertAlmostEqual(verdict.destroyed_seconds, 1.0)
        self.assertAlmostEqual(
            verdict.duplicated_seconds + verdict.destroyed_seconds,
            verdict.damaged_seconds,
        )

    def test_clean_footage_past_the_boundary_is_not_counted(self):
        # Blocks after `damaged_seconds` are readable footage with no copy in the
        # file. They must not be reported as destroyed seconds.
        verdict = nvidia_fix.duplication_verdict(
            rows([(0.0, True), (1.0, True), (2.0, False), (3.0, False)]), 2.0
        )
        self.assertAlmostEqual(verdict.duplicated_seconds, 2.0)
        self.assertAlmostEqual(verdict.destroyed_seconds, 0.0)
        self.assertEqual(verdict.scan_blocks, 4, "block denominator stays the full scan")
        self.assertAlmostEqual(verdict.matched_fraction, 0.5)

    def test_match_window_is_reported_for_the_reader(self):
        verdict = nvidia_fix.duplication_verdict(
            rows([(0.12, True), (107.54, True)]), 113.782
        )
        self.assertEqual(verdict.first_match, (0.12, 180.12))
        self.assertEqual(verdict.last_match, (107.54, 287.54))

    def test_untimed_map_is_rejected(self):
        with self.assertRaises(nvidia_fix.NvidiaFixError):
            nvidia_fix.duplication_verdict([{"t": None, "matched": True}], 10.0)


@unittest.skipUnless(REAL_MAP.is_file(), "no duplication map in recovery/")
class RecordedMapTests(unittest.TestCase):
    """The numbers AGENTS.md quotes must come out of the recorded map."""

    def test_recorded_map_gives_the_published_split(self):
        payload = json.loads(REAL_MAP.read_text(encoding="utf-8"))
        verdict = nvidia_fix.duplication_verdict(payload["rows"], 113.782)
        self.assertAlmostEqual(verdict.duplicated_seconds, 105.73, places=2)
        self.assertAlmostEqual(verdict.destroyed_seconds, 8.05, places=2)
        self.assertAlmostEqual(verdict.matched_fraction, 0.808, places=3)
        self.assertEqual(verdict.first_match, (0.12, 182.54))
        self.assertEqual(verdict.last_match, (107.54, 299.79))


if __name__ == "__main__":
    unittest.main()
