import shutil
import sys
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import desktop  # noqa: E402
from tests.helpers import corrupt_middle, make_clip  # noqa: E402

TEMP_ROOT = Path(tempfile.mkdtemp(prefix="nvidia-fix-desktop-tests-"))


def tearDownModule():
    shutil.rmtree(TEMP_ROOT, ignore_errors=True)


class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which(desktop.nvidia_fix.FFMPEG) is None:
            raise unittest.SkipTest("ffmpeg is not on PATH")
        cls.clip = make_clip(TEMP_ROOT / "desktop-input.mp4", seconds=8)
        corrupt_middle(cls.clip)

    def test_hidden_window_recovers_and_updates_results(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is not available: {exc}")
        root.withdraw()
        output = TEMP_ROOT / "desktop-output"
        app = desktop.DesktopApp(
            root,
            initial_input=str(self.clip),
            initial_output=str(output),
            test_mode=True,
        )
        try:
            app._start_recovery()
            deadline = time.time() + 60
            while app.busy and time.time() < deadline:
                root.update()
                time.sleep(0.03)
            root.update()

            self.assertFalse(app.busy, "recovery did not finish")
            self.assertIsNotNone(app.result, app.status_var.get())
            self.assertEqual(app.result["status"], "success")
            self.assertEqual(app.stat_errors.get(), "0")
            self.assertIn("Recovered and verified", app.status_var.get())
            self.assertTrue(Path(app.result["paths"]["video"]).is_file())
            self.assertTrue(Path(app.result["paths"]["audio"]).is_file())
            self.assertEqual(app.saved_path.get(), str(output))
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
