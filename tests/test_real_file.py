import os
import shutil
import tempfile
import unittest
from pathlib import Path

import nvidia_fix

REAL_INPUT = os.environ.get("NVIDIA_FIX_REAL_INPUT")

# Values established by forensic analysis of the known DVR. Kept with generous
# tolerances so decoder/container variations do not make the test brittle.
EXPECTED_LAST_BAD = 113.781922
EXPECTED_CLEAN_START = 114.031811
EXPECTED_PACKETS = 22318
EXPECTED_DURATION = 185.981444


@unittest.skipUnless(REAL_INPUT, "set NVIDIA_FIX_REAL_INPUT to run the real-file test")
class RealRecordingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(REAL_INPUT)
        if not cls.source.is_file():
            raise unittest.SkipTest(f"real input not found: {cls.source}")
        cls.out = Path(tempfile.mkdtemp(prefix="nvidia-fix-real-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def test_known_boundary_and_recovery(self):
        analysis = nvidia_fix.analyze(self.source)
        self.assertFalse(analysis.healthy)
        self.assertGreater(analysis.bad_samples, 5000)
        self.assertAlmostEqual(analysis.last_bad.pts, EXPECTED_LAST_BAD, delta=0.1)
        self.assertAlmostEqual(analysis.boundary.pts, EXPECTED_CLEAN_START, delta=0.1)

        result = nvidia_fix.process(self.source, out_dir=self.out, full_decode=True)
        self.assertEqual(result["status"], "success")

        video = result["recovery"]["video"]
        self.assertEqual(video["packets"], EXPECTED_PACKETS)
        self.assertEqual(video["decode_errors"], 0)
        self.assertAlmostEqual(video["duration_seconds"], EXPECTED_DURATION, delta=0.2)
        self.assertEqual(video["first_packet_sha256"], video["source_sample_sha256"])
        self.assertAlmostEqual(result["recovery"]["clean_start_seconds"],
                               EXPECTED_CLEAN_START, delta=0.1)

        self.assertTrue(Path(result["paths"]["video"]).is_file())
        self.assertTrue(Path(result["paths"]["audio"]).is_file())
        self.assertTrue(Path(result["paths"]["report"]).is_file())


if __name__ == "__main__":
    unittest.main()
