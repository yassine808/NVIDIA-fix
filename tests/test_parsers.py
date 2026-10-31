"""Fast, dependency-free regressions for two bugs that produced false verdicts.

1. `stss` sync-sample numbers are 1-based in ISO BMFF. Reading them as 0-based
   put the recoverable boundary one sample early and made a 108-byte non-IDR
   slice look like a keyframe.
2. ffmpeg's null muxer complains about non-monotonic dts on a perfectly good
   120 fps B-frame stream. Treating that as a decode error rejected the earliest
   clean keyframe and mislabelled a clean recovery.
"""
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "forensics"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import mp4_probe  # noqa: E402
import nvidia_fix  # noqa: E402


def stss_box(sample_numbers):
    body = struct.pack(">I", 0)                      # version + flags
    body += struct.pack(">I", len(sample_numbers))   # entry count
    body += b"".join(struct.pack(">I", n) for n in sample_numbers)
    return body, 0, len(body)


class SyncSampleTests(unittest.TestCase):
    def test_stss_is_converted_from_one_based(self):
        buf, start, end = stss_box([1, 31, 61])
        self.assertEqual(mp4_probe.parse_stss(buf, start, end), [0, 30, 60])

    def test_boundary_keyframe_is_not_off_by_one(self):
        # 1-based 13681 is the IDR at 0-based index 13680; both must agree with
        # the ffprobe packet index the engine acts on.
        buf, start, end = stss_box([13651, 13681])
        syncs = mp4_probe.parse_stss(buf, start, end)
        self.assertEqual(syncs, [13650, 13680])
        self.assertNotIn(13651, syncs)


class DecodeClassificationTests(unittest.TestCase):
    MUXER = ("[null @ 00000253] Application provided invalid, non monotonically "
             "increasing dts to muxer in stream 0: 18161 >= 18161")

    def test_muxer_dts_warning_is_not_a_decode_error(self):
        check = nvidia_fix._classify_stderr([self.MUXER, self.MUXER])
        self.assertEqual(check.errors, [])
        self.assertEqual(len(check.warnings), 2)
        self.assertTrue(check.ok, "timestamp warnings must not reject a clean cut")

    def test_decoder_error_blocks(self):
        check = nvidia_fix._classify_stderr(
            ["[h264 @ 000001] error while decoding MB 12 34, bytestream 500"]
        )
        self.assertEqual(len(check.errors), 1)
        self.assertFalse(check.ok)

    def test_corrupt_packet_and_reference_gaps_block(self):
        check = nvidia_fix._classify_stderr([
            "[mp4 @ 000001] Packet corrupt (stream = 0, dts = 123)",
            "[h264 @ 000001] Frame num change from 5 to 6",
        ])
        self.assertEqual(len(check.errors), 2)
        self.assertFalse(check.ok)

    def test_unknown_output_is_surfaced_not_hidden(self):
        check = nvidia_fix._classify_stderr(["something nobody predicted"])
        self.assertEqual(check.errors, [])
        self.assertEqual(check.unclassified, ["something nobody predicted"])


if __name__ == "__main__":
    unittest.main()
