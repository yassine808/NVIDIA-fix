import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEMP_ROOT = Path(tempfile.mkdtemp(prefix="nvidia-fix-tests-"))

import app as webapp  # noqa: E402
import nvidia_fix  # noqa: E402
from tests.helpers import corrupt_middle, make_clip, run  # noqa: E402


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tearDownModule():
    shutil.rmtree(TEMP_ROOT, ignore_errors=True)


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clean = make_clip(TEMP_ROOT / "clean.mp4", seconds=8, with_audio=True)
        cls.corrupt = make_clip(TEMP_ROOT / "corrupt.mp4", seconds=8, with_audio=True)
        cls.corrupted_samples = corrupt_middle(cls.corrupt)

    def test_clean_file_is_healthy(self):
        analysis = nvidia_fix.analyze(self.clean)
        self.assertTrue(analysis.healthy)
        self.assertEqual(analysis.bad_samples, 0)
        self.assertEqual(analysis.candidates, [])

        out = TEMP_ROOT / "healthy-out"
        result = nvidia_fix.process(self.clean, out_dir=out)
        self.assertEqual(result["status"], "healthy")
        self.assertIsNone(result["recovery"])
        self.assertFalse(out.exists() and any(out.iterdir()))

    def test_detects_corruption_boundary(self):
        analysis = nvidia_fix.analyze(self.corrupt)
        self.assertFalse(analysis.healthy)
        self.assertEqual(analysis.bad_samples, self.corrupted_samples)
        self.assertAlmostEqual(analysis.first_bad.pts, 2.5, delta=0.15)
        self.assertGreaterEqual(analysis.last_bad.pts, 3.5)
        self.assertLess(analysis.last_bad.pts, 3.95)
        self.assertTrue(analysis.candidates)
        self.assertAlmostEqual(analysis.boundary.pts, 4.0, delta=0.15)
        self.assertGreaterEqual(analysis.clean_run, 30)

    def test_recovers_tail(self):
        before = sha256(self.corrupt)
        out = TEMP_ROOT / "recovered"
        messages = []
        result = nvidia_fix.process(
            self.corrupt, out_dir=out, full_decode=True, progress=messages.append
        )

        self.assertEqual(result["status"], "success")
        self.assertTrue(any("Cutting the clean tail" in m for m in messages))
        video = result["recovery"]["video"]
        self.assertGreaterEqual(video["packets"], 100)
        self.assertEqual(video["decode_errors"], 0)
        self.assertGreater(video["duration_seconds"], 3.5)
        self.assertLess(video["duration_seconds"], 4.5)
        self.assertEqual(video["first_packet_sha256"], video["source_sample_sha256"])

        self.assertTrue(Path(result["paths"]["video"]).is_file())
        self.assertTrue(Path(result["paths"]["audio"]).is_file())
        report = Path(result["paths"]["report"])
        self.assertTrue(report.is_file())
        report_doc = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(report_doc["recovery"]["video"]["decode_errors"], 0)
        self.assertEqual(before, sha256(self.corrupt), "input file was modified")

    def test_cli_analyze_json(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "nvidia_fix.py"), "analyze",
             str(self.corrupt), "--json"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["status"], "recoverable")
        self.assertAlmostEqual(data["corruption"]["clean_start_seconds"], 4.0, delta=0.15)

    def test_audio_only_file_is_rejected(self):
        audio = TEMP_ROOT / "audio-only.m4a"
        run([
            nvidia_fix.FFMPEG, "-hide_banner", "-v", "error", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:a", "aac", str(audio),
        ])
        with self.assertRaises(nvidia_fix.UnsupportedMediaError):
            nvidia_fix.analyze(audio)


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = webapp.app.test_client()
        cls.clip = make_clip(TEMP_ROOT / "web-input.mp4", seconds=8, with_audio=True)
        corrupt_middle(cls.clip)

    def _fix(self, payload):
        return self.client.post("/api/fix", json=payload)

    def tearDown(self):
        for path in TEMP_ROOT.glob("web-input.clean*"):
            path.unlink()

    def test_api_recovers_beside_the_original(self):
        response = self._fix({"path": str(self.clip), "full_decode": True})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        data = response.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["original_name"], "web-input.mp4")
        self.assertEqual(data["original_path"], str(self.clip.resolve()))

        video = Path(data["paths"]["video"])
        self.assertEqual(video.parent, self.clip.resolve().parent)
        self.assertEqual(video.name, "web-input.clean.mp4")
        self.assertTrue(video.is_file())
        self.assertTrue(Path(data["paths"]["audio"]).is_file())
        self.assertTrue(Path(data["paths"]["report"]).is_file())
        self.assertEqual(len(data["outputs"]), 3)

    def test_result_page_lists_the_outputs(self):
        response = self.client.post(
            "/fix",
            data={"video_path": f'"{self.clip}"', "full_decode": "1"},
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        page = response.get_data(as_text=True)
        self.assertIn("Clean video", page)
        self.assertIn("web-input.clean.mp4", page)
        self.assertIn(str(self.clip.resolve().parent), page)

    def test_rejects_wrong_extension(self):
        notes = TEMP_ROOT / "notes.txt"
        notes.write_text("not a video", encoding="utf-8")
        response = self._fix({"path": str(notes)})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported file type", response.get_json()["error"])

    def test_rejects_missing_path(self):
        response = self._fix({})
        self.assertEqual(response.status_code, 400)
        self.assertIn("path", response.get_json()["error"].lower())

    def test_rejects_nonexistent_file(self):
        response = self._fix({"path": str(TEMP_ROOT / "nope.mp4")})
        self.assertEqual(response.status_code, 400)
        self.assertIn("No file exists", response.get_json()["error"])

    def test_health_endpoint(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")


if __name__ == "__main__":
    unittest.main()
