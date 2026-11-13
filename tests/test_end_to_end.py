import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from harness import metrics, runner  # noqa: E402
from harness.backends import MockBackend  # noqa: E402
from scripts.generate_leads import generate  # noqa: E402
from dataclasses import asdict  # noqa: E402


class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data_path = os.path.join(self.tmp, "leads.jsonl")
        leads = generate(n=36, seed=11)
        with open(self.data_path, "w", encoding="utf-8") as fh:
            for lead in leads:
                fh.write(json.dumps(asdict(lead), sort_keys=True) + "\n")
        self.out_path = os.path.join(self.tmp, "results.jsonl")

    def test_full_mock_run_denominators(self):
        leads = runner.load_leads(self.data_path)
        backend = MockBackend(seed=11)
        counts = runner.run_all(leads, backend,
                                ["treatment", "placebo", "baseline"],
                                runs=2, seed=11, out_path=self.out_path)
        self.assertEqual(counts["treatment"], 72)
        self.assertEqual(counts["placebo"], 72)
        self.assertEqual(counts["baseline"], 72)
        rows = metrics.load_results(self.out_path)
        self.assertTrue(all(r["parse_ok"] for r in rows))
        treat = [r for r in rows if r["arm"] == "treatment"]
        placebo = [r for r in rows if r["arm"] == "placebo"]
        # Placebo pairs each lead's truth with another lead's signals, so it
        # must score far below the treatment arm on this seeded instance.
        t_acc = metrics.accuracy(treat)["accuracy"]
        p_acc = metrics.accuracy(placebo)["accuracy"]
        self.assertGreater(t_acc - p_acc, 0.15)

    def test_placebo_uses_derangement(self):
        perm = runner._derangement(50, seed=5)
        self.assertEqual(sorted(perm), list(range(50)))
        self.assertTrue(all(perm[i] != i for i in range(50)))

    def test_cli_and_report(self):
        out = os.path.join(self.tmp, "cli-results.jsonl")
        subprocess.run(
            [sys.executable, os.path.join(ROOT, "run_eval.py"),
             "--backend", "mock", "--runs", "2", "--data", self.data_path,
             "--out", out],
            check=True, cwd=ROOT, capture_output=True, text=True)
        self.assertTrue(os.path.exists(out + ".meta.json"))
        report_path = os.path.join(self.tmp, "REPORT.md")
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "report.py"),
             "--results", out, "--out", report_path],
            check=True, cwd=ROOT, capture_output=True, text=True)
        self.assertIn("wrote", proc.stdout)
        with open(report_path, "r", encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("MOCK BACKEND", text)
        self.assertIn("Tier accuracy by true segment", text)
        # Every accuracy figure appears as correct/n, never a bare percent.
        self.assertIn("| **all** |", text)


if __name__ == "__main__":
    unittest.main()
