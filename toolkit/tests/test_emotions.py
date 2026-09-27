import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CPM = Path(__file__).resolve().parents[1] / "bin" / "cpm"


def run(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


class EmotionsReadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "demo-app"
        self.repo.mkdir()
        run(["git", "init", "-q"], self.repo)
        run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init"], self.repo)
        self.env = {**os.environ, "CPM_PROJECT": "demo", "CPM_CONFIG_HOME": self.tmp.name,
                    "EMOTION_LEDGER": str(Path(self.tmp.name) / "ledger.jsonl")}

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, name, lines, message):
        (self.repo / name).write_text("x\n" * lines)
        run(["git", "add", "-A"], self.repo)
        run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message], self.repo)

    def read(self):
        out = subprocess.run([sys.executable, str(CPM), "emotions", "read", str(self.repo), "--range", "HEAD~1..HEAD"],
                             env=self.env, capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def test_tiny_slip_is_amused_and_low(self):
        self.commit("a.txt", 2, "fix(ui): forgot the label")
        d = self.read()
        self.assertEqual((d["emotion"], d["intensity"]), ("amused", 1))
        self.assertEqual(d["triggers"][0], "tasks")

    def test_big_feature_is_intense_and_plain_first(self):
        for i in range(6):
            (self.repo / f"mod{i}").mkdir()
            (self.repo / f"mod{i}" / "f.py").write_text("x\n" * 400)
        self.commit("billing.txt", 10, "feat(billing): paywall with yearly plan")
        d = self.read()
        self.assertEqual(d["emotion"], "satisfied")
        self.assertGreaterEqual(d["intensity"], 4)
        self.assertEqual(d["triggers"], ["tasks", "money"])
        self.assertTrue(d["note"].startswith("Paywall with yearly plan. A big, involved change."))


if __name__ == "__main__":
    unittest.main()
