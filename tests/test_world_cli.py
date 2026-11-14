"""v2 command-line path end to end, with no model: the mock backend, and
a fake `claude` script standing in for the CLI where the real-backend
code path (subprocess, fail-fast, scratch directory) needs exercising."""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import worldkit  # noqa: E402
from worldkit import ROOT, run_script  # noqa: E402

from harness import prereg, report  # noqa: E402

MANIFEST = os.path.join(ROOT, prereg.MANIFEST_PATH)


class CliCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.data = worldkit.write_dataset(self.tmp, n=12, seed=4)

    def path(self, name):
        return os.path.join(self.tmp, name)


class TestMockEndToEnd(CliCase):
    def test_run_grade_report(self):
        run_dir = self.path("run")
        proc = run_script(ROOT, "run_world_eval.py", "--backend", "mock",
                          "--data", self.data, "--runs", "2",
                          "--run-dir", run_dir)
        out = json.loads(proc.stdout)
        self.assertEqual(out["state"], "complete")
        self.assertEqual(out["counts"]["planned_trials"], 72)
        self.assertEqual(out["counts"]["model_calls"], 48)
        self.assertEqual(out["counts"]["worlds"], 6)

        grade_path = self.path("grade.json")
        proc = run_script(ROOT, "scripts/grade_world.py", "--run-dir",
                          run_dir, "--data", self.data, "--out", grade_path)
        self.assertIn("MOCK", proc.stdout)
        self.assertIn("all integrity checks passed", proc.stdout)
        with open(grade_path) as fh:
            grade = json.load(fh)
        self.assertEqual(grade["grading"], "v2-world-state")
        self.assertFalse(grade["run"]["preregistered"])
        for arm in ("treatment", "placebo", "baseline"):
            self.assertEqual(grade["arms"][arm]["tier_effect"]["n"], 24)
            self.assertEqual(grade["arms"][arm]["independent_leads"], 12)
        self.assertEqual(len(grade["comparisons"]), 4)
        self.assertEqual(grade["comparisons"][0]["n_leads"], 12)

        report_path = self.path("REPORT.md")
        run_script(ROOT, "scripts/world_report.py", "--run-dir", run_dir,
                   "--data", self.data, "--out", report_path)
        with open(report_path) as fh:
            text = fh.read()
        self.assertIn("MOCK BACKEND", text)
        self.assertIn("v2 world-state report", text)
        self.assertIn("Planned comparisons (paired per lead)", text)
        self.assertNotIn("Prespecified criteria", text)
        # Rendering again, later, gives the same bytes: no wall clock.
        again = self.path("REPORT-again.md")
        run_script(ROOT, "scripts/world_report.py", "--run-dir", run_dir,
                   "--data", self.data, "--out", again)
        with open(again) as fh:
            self.assertEqual(fh.read(), text)

    def test_existing_run_dir_is_refused(self):
        run_dir = self.path("run")
        args = ("--backend", "mock", "--data", self.data, "--runs", "1",
                "--run-dir", run_dir)
        run_script(ROOT, "run_world_eval.py", *args)
        before = worldkit.dir_digest(run_dir)
        proc = run_script(ROOT, "run_world_eval.py", *args, check=False)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("never overwritten", proc.stderr)
        self.assertEqual(worldkit.dir_digest(run_dir), before)

    def test_grader_fails_closed_on_tampered_world(self):
        run_dir = self.path("run")
        run_script(ROOT, "run_world_eval.py", "--backend", "mock",
                   "--data", self.data, "--runs", "1", "--run-dir", run_dir)
        worldkit.edit_world(run_dir, [
            "UPDATE crm_leads SET tier = 'enterprise'"], resealed=False)
        grade_path = self.path("grade.json")
        for script, out in (("scripts/grade_world.py", grade_path),
                            ("scripts/world_report.py", self.path("R.md"))):
            proc = run_script(ROOT, script, "--run-dir", run_dir, "--data",
                              self.data, "--out", out, check=False)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("NOT GRADED", proc.stderr)
            self.assertFalse(os.path.exists(out))  # no score, no report

    def test_wrong_dataset_is_refused(self):
        run_dir = self.path("run")
        run_script(ROOT, "run_world_eval.py", "--backend", "mock",
                   "--data", self.data, "--runs", "1", "--run-dir", run_dir)
        other = worldkit.write_dataset(self.tmp, n=12, seed=5,
                                       name="other.jsonl")
        proc = run_script(ROOT, "scripts/grade_world.py", "--run-dir",
                          run_dir, "--data", other, check=False)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("dataset hash mismatch", proc.stderr)

    def test_prereg_manifest_cannot_be_attached_to_unregistered_run(self):
        run_dir = self.path("run")
        run_script(ROOT, "run_world_eval.py", "--backend", "mock",
                   "--data", self.data, "--runs", "1", "--run-dir", run_dir)
        proc = run_script(ROOT, "scripts/grade_world.py", "--run-dir",
                          run_dir, "--data", self.data, "--prereg",
                          MANIFEST, check=False)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not preregistered", proc.stderr)


class TestRealBackendPathWithFakeCli(CliCase):
    """`--backend claude-code` pointed at a fake script. No model."""

    def real_args(self, command, run_dir):
        return ("--backend", "claude-code", "--exploratory-unregistered",
                "--model", "some-model", "--command", command, "--data",
                self.data, "--runs", "1", "--run-dir", run_dir)

    def test_real_model_run_needs_prereg_or_explicit_exploratory(self):
        fake, log = worldkit.write_fake_claude(self.tmp)
        proc = run_script(ROOT, "run_world_eval.py", "--backend",
                          "claude-code", "--command", fake, "--data",
                          self.data, "--run-dir", self.path("run"),
                          check=False)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("preregistered", proc.stderr)
        self.assertEqual(worldkit.fake_calls(log), [])
        self.assertFalse(os.path.exists(self.path("run")))

    def test_exploratory_run_is_tool_free_stateless_and_out_of_repo(self):
        fake, log = worldkit.write_fake_claude(self.tmp)
        run_dir = self.path("run")
        run_script(ROOT, "run_world_eval.py",
                   *self.real_args(fake, run_dir))
        calls = worldkit.fake_calls(log)
        self.assertEqual(len(calls), 24)  # treatment + placebo, 12 leads
        for line in calls:
            argv, cwd, listing = line.split("|")
            self.assertIn("--model some-model", argv)
            self.assertIn("--tools  --no-session-persistence", argv)
            self.assertNotEqual(os.path.realpath(cwd),
                                os.path.realpath(ROOT))
            self.assertEqual(listing, "*")  # empty working directory
        with open(os.path.join(run_dir, "receipt.json")) as fh:
            receipt = json.load(fh)
        self.assertEqual(receipt["kind"], "exploratory")
        self.assertFalse(receipt["preregistered"])
        # No machine-local path is recorded.
        self.assertNotIn(self.tmp, json.dumps(receipt))
        self.assertEqual(receipt["backend"]["launcher"],
                         "custom launcher (path not recorded)")
        with open(os.path.join(run_dir, "manifest.json")) as fh:
            self.assertEqual(json.load(fh)["cli_reported_models"],
                             ["claude-fable-5-2"])
        report_path = self.path("R.md")
        run_script(ROOT, "scripts/world_report.py", "--run-dir", run_dir,
                   "--data", self.data, "--out", report_path)
        with open(report_path) as fh:
            text = fh.read()
        self.assertIn("NOT PREREGISTERED", text)
        self.assertNotIn("MOCK", text)

    def test_cli_failure_preserves_partial_and_previous_complete(self):
        good_fake, _ = worldkit.write_fake_claude(self.tmp, name="good")
        good = self.path("good-run")
        run_script(ROOT, "run_world_eval.py",
                   *self.real_args(good_fake, good))
        before = worldkit.dir_digest(good)

        bad_fake, log = worldkit.write_fake_claude(self.tmp, fail_at=7,
                                                   name="bad")
        bad = self.path("bad-run")
        proc = run_script(ROOT, "run_world_eval.py",
                          *self.real_args(bad_fake, bad), check=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("aborted on the first CLI failure", proc.stderr)
        self.assertEqual(len(worldkit.fake_calls(log)), 7)  # no retries
        self.assertFalse(os.path.exists(bad))
        partial = bad + ".partial"
        with open(os.path.join(partial, "ABORTED.json")) as fh:
            self.assertEqual(json.load(fh)["decisions_logged"], 6)
        self.assertFalse(os.path.exists(os.path.join(partial,
                                                     "manifest.json")))
        proc = run_script(ROOT, "scripts/grade_world.py", "--run-dir",
                          partial, "--data", self.data, check=False)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("NOT GRADED", proc.stderr)
        # Retrying into the same place is refused; the partial stays.
        proc = run_script(ROOT, "run_world_eval.py",
                          *self.real_args(good_fake, bad), check=False)
        self.assertEqual(proc.returncode, 2)
        self.assertTrue(os.path.exists(os.path.join(partial,
                                                    "ABORTED.json")))
        # The earlier complete run is byte-identical and still grades.
        self.assertEqual(worldkit.dir_digest(good), before)
        run_script(ROOT, "scripts/grade_world.py", "--run-dir", good,
                   "--data", self.data)

    def test_missing_cli_fails_before_creating_anything(self):
        run_dir = self.path("run")
        proc = run_script(ROOT, "run_world_eval.py", *self.real_args(
            self.path("no-such-cli"), run_dir), check=False)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(os.path.exists(run_dir))
        self.assertFalse(os.path.exists(run_dir + ".partial"))


class TestLegacyMode(CliCase):
    def test_new_legacy_runs_record_their_date_and_label(self):
        out = self.path("legacy.jsonl")
        run_script(ROOT, "run_eval.py", "--backend", "mock", "--runs", "1",
                   "--data", self.data, "--out", out)
        with open(out + ".meta.json") as fh:
            meta = json.load(fh)
        self.assertEqual(meta["grading"], "v1-legacy-log")
        text = report.build_report(out)
        self.assertIn(f"run completed {meta['completed_at_utc']}", text)
        self.assertIn("(v1 legacy grading)", text.splitlines()[0])
        self.assertIn("V1 LEGACY GRADING", text)
        self.assertIn("no CRM world-state evidence", text)
        self.assertEqual(text, report.build_report(out))

    def test_v1_metadata_without_a_date_says_so(self):
        cwd = os.getcwd()
        os.chdir(ROOT)
        try:
            text = report.build_report("results/results.jsonl")
        finally:
            os.chdir(cwd)
        self.assertIn("run date not recorded", text)
        self.assertIn("V1 LEGACY GRADING", text)
        self.assertNotIn("world database", text)


class TestFreshness(unittest.TestCase):
    def test_tracked_reports_match_their_data(self):
        proc = run_script(ROOT, "scripts/check_freshness.py", check=False)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        for name in ("REPORT.md", "results/EXAMPLE-REPORT-mock.md",
                     "results/v2-mock-example/grade.json",
                     "results/v2-mock-example/REPORT-MOCK.md"):
            self.assertIn(f"fresh   {name}", proc.stdout)

    def test_stale_or_hand_edited_report_is_caught(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        root = os.path.join(tmp, "copy")
        os.makedirs(root)
        shutil.copy(os.path.join(ROOT, "REPORT.md"), root)
        for name in ("results", "data", "docs", "harness", "scripts"):
            shutil.copytree(os.path.join(ROOT, name),
                            os.path.join(root, name),
                            ignore=shutil.ignore_patterns("__pycache__",
                                                          "smoke*"))
        shutil.copy(os.path.join(ROOT, "run_world_eval.py"), root)
        check = ("scripts/check_freshness.py", "--root", root)
        self.assertEqual(run_script(ROOT, *check, check=False).returncode,
                         0)
        # A hand-edited number in the real v1 report.
        path = os.path.join(root, "REPORT.md")
        with open(path) as fh:
            text = fh.read()
        self.assertIn("357/360", text)
        with open(path, "w") as fh:
            fh.write(text.replace("357/360", "360/360"))
        proc = run_script(ROOT, *check, check=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("STALE   REPORT.md", proc.stdout)
        with open(path, "w") as fh:
            fh.write(text)
        # A hand-edited number in the v2 mock report.
        path = os.path.join(root, "results/v2-mock-example/REPORT-MOCK.md")
        with open(path) as fh:
            text = fh.read()
        with open(path, "w") as fh:
            fh.write(text.replace("214/360", "360/360"))
        proc = run_script(ROOT, *check, check=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("STALE   results/v2-mock-example/REPORT-MOCK.md",
                      proc.stdout)
        with open(path, "w") as fh:
            fh.write(text)
        # An edited mock world is not re-graded around.
        worldkit.edit_world(
            os.path.join(root, "results/v2-mock-example"),
            ["UPDATE crm_leads SET tier = 'team'"], resealed=False)
        proc = run_script(ROOT, *check, check=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("not gradeable", proc.stdout)


if __name__ == "__main__":
    unittest.main()
