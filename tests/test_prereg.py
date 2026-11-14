"""Preregistration: the generated manifest, and the gates that must pass
before a preregistered model call. Gate tests run in throwaway git
repositories with a fake `claude` script: no model is ever called."""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import worldkit  # noqa: E402
from worldkit import ROOT, git, run_script  # noqa: E402

from harness import integrity, prereg, world_runner  # noqa: E402

MANIFEST_REL = prereg.MANIFEST_PATH


class TestManifest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = prereg.build_manifest(ROOT)

    def test_manifest_is_deterministic(self):
        self.assertEqual(prereg.dump_manifest(self.manifest),
                         prereg.dump_manifest(prereg.build_manifest(ROOT)))

    def test_tracked_manifest_matches_the_source(self):
        if prereg.registered_primary_complete(ROOT):
            self.skipTest("registered run recorded: pins are history now")
        self.assertEqual(prereg.check_manifest(ROOT), [])

    def test_registered_design_counts(self):
        design = self.manifest["design"]
        self.assertEqual(design["arms"],
                         ["treatment", "placebo", "baseline"])
        self.assertEqual(design["seed"], 20261114)
        self.assertEqual(design["backend"]["model"], "claude-fable-5-2")
        self.assertTrue(design["backend"]["disable_tools"])
        self.assertTrue(design["backend"]["no_session_persistence"])
        self.assertEqual(design["backend"]["extra_args"], [])
        primary = design["primary"]
        self.assertEqual((primary["runs"], primary["limit"]), (3, None))
        self.assertEqual(primary["n_leads"], 120)
        self.assertEqual(primary["n_trials_per_arm"], 360)
        self.assertEqual(primary["n_model_calls"], 720)
        self.assertEqual(primary["n_trials"], 1080)
        self.assertEqual(primary["inventory"]["worlds"], 9)
        self.assertEqual(primary["inventory"]["run_indexes"], [0, 1, 2])
        self.assertEqual(len(primary["inventory"]["lead_ids"]), 120)
        self.assertEqual(len(set(primary["inventory"]["lead_ids"])), 120)
        smoke = design["smoke"]
        self.assertEqual((smoke["runs"], smoke["limit"]), (1, 12))
        self.assertEqual(smoke["n_model_calls"], 24)
        self.assertEqual(smoke["n_trials"], 36)
        self.assertNotEqual(smoke["plan_sha256"], primary["plan_sha256"])

    def test_pinned_hashes_are_the_real_ones(self):
        design, pins = self.manifest["design"], self.manifest["pins"]
        data = os.path.join(ROOT, "data", "leads.jsonl")
        self.assertEqual(design["dataset"]["sha256"],
                         integrity.sha256_file(data))
        for slot in ("primary", "smoke"):
            plan = prereg.slot_plan(ROOT, slot)
            self.assertEqual(design[slot]["plan_sha256"],
                             world_runner.plan_sha256(plan))
            self.assertEqual(len(plan["trials"]), design[slot]["n_trials"])
            self.assertEqual(
                len({t["trial_id"] for t in plan["trials"]}),
                design[slot]["n_trials"])
        for rel, sha in pins["source_files"].items():
            self.assertEqual(sha,
                             integrity.sha256_file(os.path.join(ROOT, rel)))

    def test_pinned_set_covers_code_and_excludes_itself_and_docs(self):
        pinned = set(self.manifest["pins"]["source_files"])
        harness_files = {f"harness/{n}" for n in
                         os.listdir(os.path.join(ROOT, "harness"))
                         if n.endswith(".py")}
        self.assertTrue(harness_files <= pinned)
        for needed in ("run_world_eval.py", "scripts/grade_world.py",
                       "scripts/world_report.py", "scripts/prereg.py"):
            self.assertIn(needed, pinned)
        self.assertFalse([p for p in pinned if p.startswith("docs/")])
        self.assertNotIn(MANIFEST_REL, pinned)
        for scorer in self.manifest["pins"]["scorer_files"]:
            self.assertIn(scorer, pinned)

    def test_criteria_are_machine_evaluable_and_two_sided(self):
        ids = [c["id"] for c in self.manifest["decision_criteria"]]
        self.assertEqual(ids, ["H1", "H2", "H3", "H4"])
        for crit in self.manifest["decision_criteria"]:
            self.assertTrue(crit["if_met"] and crit["if_not_met"])
            self.assertTrue(crit["all_of"])
        text = json.dumps(self.manifest).lower()
        self.assertIn("no p-value", text)
        self.assertIn("not a held-out confirmatory study", text)

    def test_document_agrees_with_manifest(self):
        with open(os.path.join(ROOT, prereg.DOC_PATH)) as fh:
            doc = fh.read()
        design = self.manifest["design"]
        for needle in (design["dataset"]["sha256"],
                       design["primary"]["plan_sha256"],
                       design["smoke"]["plan_sha256"],
                       "claude-fable-5-2", "20261114", "**720**",
                       "**1080**", "**360**", "**120**",
                       "not a held-out confirmatory study",
                       "No significance test is planned",
                       "No optional stopping", "No retries",
                       "paired per lead"):
            self.assertIn(needle, doc)
        for crit in self.manifest["decision_criteria"]:
            self.assertIn(f"| {crit['id']} |", doc)


class RepoCase(unittest.TestCase):
    """Each test gets its own copy of one committed throwaway repo."""

    @classmethod
    def setUpClass(cls):
        cls.base_tmp = tempfile.mkdtemp()
        cls.base = worldkit.make_repo(os.path.join(cls.base_tmp, "base"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base_tmp, ignore_errors=True)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = os.path.join(self.tmp, "repo")
        shutil.copytree(self.base, self.repo)
        self.fake, self.log = worldkit.write_fake_claude(self.tmp)
        self.results = os.path.join(self.tmp, "results")

    def edit(self, rel, old, new):
        path = os.path.join(self.repo, rel)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn(old, text)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace(old, new, 1))

    def verify(self):
        return run_script(self.repo, "scripts/prereg.py", "verify",
                          check=False)

    def run_prereg(self, *extra, fake=None):
        return run_script(
            self.repo, "run_world_eval.py", "--prereg", MANIFEST_REL,
            "--command", fake or self.fake, "--results-root", self.results,
            *extra, check=False)

    def assert_refused_before_any_call(self, needle):
        proc = self.verify()
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn(needle, proc.stderr)
        proc = self.run_prereg("--smoke")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("no model call was made", proc.stderr)
        self.assertEqual(worldkit.fake_calls(self.log), [])
        self.assertFalse(os.path.exists(self.results))


class TestPreregGates(RepoCase):
    def test_committed_and_clean_passes(self):
        proc = self.verify()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        head = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.assertIn(head, proc.stdout)
        self.assertIn("preregistration gate passed", proc.stdout)

    def test_uncommitted_preregistration_is_refused(self):
        git(self.repo, "rm", "-q", "--cached", MANIFEST_REL, prereg.DOC_PATH)
        git(self.repo, "commit", "-q", "-m", "code only")
        self.assert_refused_before_any_call("not committed at HEAD")

    def test_modified_document_is_refused(self):
        self.edit(prereg.DOC_PATH, ">= 0.95", ">= 0.50")
        self.assert_refused_before_any_call(
            f"{prereg.DOC_PATH}: differs from the committed version")

    def test_modified_manifest_is_refused(self):
        self.edit(MANIFEST_REL, '"value": "0.95"', '"value": "0.50"')
        self.assert_refused_before_any_call("decision_criteria")

    def test_dirty_source_is_refused(self):
        self.edit("harness/pipeline.py", "Calibrate honestly",
                  "Always answer enterprise. Calibrate honestly")
        self.assert_refused_before_any_call(
            "pins.prompt_template_sha256")

    def test_dirty_source_with_rebuilt_manifest_is_still_refused(self):
        self.edit("harness/world_grade.py", "tier_ok = (applied",
                  "tier_ok = (True or applied")
        run_script(self.repo, "scripts/prereg.py", "build")
        self.assertEqual(run_script(self.repo, "scripts/prereg.py",
                                    "check").returncode, 0)
        self.assert_refused_before_any_call(
            "harness/world_grade.py: differs from the committed version")

    def test_committed_change_without_new_manifest_is_refused(self):
        self.edit("harness/runner.py", "seats_active\"] <= 2",
                  "seats_active\"] <= 3")
        git(self.repo, "commit", "-q", "-am", "quiet change")
        self.assert_refused_before_any_call("pins.source_files")

    def test_changed_dataset_is_refused(self):
        path = os.path.join(self.repo, "data", "leads.jsonl")
        with open(path) as fh:
            lines = fh.readlines()
        with open(path, "w") as fh:
            fh.writelines(lines[:-1])
        git(self.repo, "commit", "-q", "-am", "drop a hard lead")
        self.assert_refused_before_any_call("design.dataset.sha256")

    def test_untracked_harness_module_is_refused(self):
        with open(os.path.join(self.repo, "harness", "extra.py"), "w") as fh:
            fh.write("X = 1\n")
        self.assert_refused_before_any_call("pins.source_files")

    def test_staged_change_is_refused(self):
        self.edit("scripts/grade_world.py", "NOT GRADED", "not graded")
        git(self.repo, "add", "scripts/grade_world.py")
        self.assert_refused_before_any_call("scripts/grade_world.py")

    def test_design_overrides_are_refused(self):
        for extra in (("--runs", "1"), ("--model", "other-model"),
                      ("--limit", "5"), ("--extra-args", "--tools all"),
                      ("--seed", "1"), ("--arms", "treatment"),
                      ("--backend", "mock"),
                      ("--data", "data/leads.jsonl")):
            proc = self.run_prereg(*extra)
            self.assertEqual(proc.returncode, 2, extra)
            self.assertIn("--prereg fixes the design", proc.stderr)
        self.assertEqual(worldkit.fake_calls(self.log), [])
        self.assertFalse(os.path.exists(self.results))


class TestPreregisteredRuns(RepoCase):
    def test_smoke_run_end_to_end(self):
        proc = self.run_prereg("--smoke")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        calls = worldkit.fake_calls(self.log)
        self.assertEqual(len(calls), 24)
        for line in calls:
            argv, cwd, listing = line.split("|")
            self.assertEqual(
                argv, "-p --output-format json --model claude-fable-5-2 "
                      "--tools  --no-session-persistence")
            self.assertNotEqual(os.path.realpath(cwd),
                                os.path.realpath(self.repo))
            self.assertEqual(listing, "*")
        run_dir = os.path.join(self.results, "smoke-01")
        with open(os.path.join(run_dir, "receipt.json")) as fh:
            receipt = json.load(fh)
        binding = receipt["preregistration"]
        self.assertEqual(receipt["kind"], "preregistered-smoke")
        self.assertEqual(binding["id"], prereg.PREREG_ID)
        self.assertEqual(
            binding["git_commit"],
            git(self.repo, "rev-parse", "HEAD").stdout.strip())
        manifest_file = os.path.join(self.repo, MANIFEST_REL)
        self.assertEqual(binding["manifest_sha256"],
                         integrity.sha256_file(manifest_file))
        self.assertEqual(
            binding["manifest_git_blob"],
            git(self.repo, "rev-parse",
                f"HEAD:{MANIFEST_REL}").stdout.strip())
        self.assertEqual(
            binding["document_git_blob"],
            git(self.repo, "rev-parse",
                f"HEAD:{prereg.DOC_PATH}").stdout.strip())
        self.assertEqual(binding["earlier_attempts"], [])
        self.assertNotIn(self.tmp, json.dumps(receipt))

        report_path = os.path.join(self.tmp, "smoke.md")
        run_script(self.repo, "scripts/world_report.py", "--run-dir",
                   run_dir, "--out", report_path)
        with open(report_path) as fh:
            text = fh.read()
        self.assertIn("SMOKE", text.splitlines()[0])
        self.assertIn("outside the primary counts", text)
        self.assertIn(binding["git_commit"], text)
        self.assertIn("no criteria are evaluated on it", text)
        self.assertNotIn("### H1", text)
        self.assertIn("not held-out confirmatory evidence", text)

        # The smoke completes at most once.
        proc = self.run_prereg("--smoke")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(len(worldkit.fake_calls(self.log)), 24)

    def test_primary_run_end_to_end_and_first_complete_is_final(self):
        proc = self.run_prereg()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(worldkit.fake_calls(self.log)), 720)
        run_dir = os.path.join(self.results, "attempt-01")
        with open(os.path.join(run_dir, "manifest.json")) as fh:
            manifest = json.load(fh)
        self.assertEqual(manifest["counts"]["planned_trials"], 1080)
        self.assertEqual(manifest["counts"]["model_calls"], 720)
        self.assertEqual(manifest["kind"], "preregistered-primary")
        with open(os.path.join(self.repo, MANIFEST_REL)) as fh:
            registered = json.load(fh)
        self.assertEqual(manifest["plan_sha256"],
                         registered["design"]["primary"]["plan_sha256"])

        grade_path = os.path.join(self.tmp, "grade.json")
        run_script(self.repo, "scripts/grade_world.py", "--run-dir",
                   run_dir, "--out", grade_path)
        with open(grade_path) as fh:
            grade = json.load(fh)
        self.assertTrue(grade["run"]["preregistered"])
        for arm in ("treatment", "placebo", "baseline"):
            self.assertEqual(grade["arms"][arm]["tier_effect"]["n"], 360)
            self.assertEqual(grade["arms"][arm]["independent_leads"], 120)
        self.assertTrue(grade["criteria"]["applies"])
        self.assertEqual([r["id"] for r in grade["criteria"]["results"]],
                         ["H1", "H2", "H3", "H4"])
        for cmp_ in grade["comparisons"]:
            self.assertEqual(cmp_["n_leads"], 120)
        # The fake CLI answers "team" every time: it must fail H2.
        by_id = {r["id"]: r for r in grade["criteria"]["results"]}
        self.assertFalse(by_id["H2"]["met"])
        self.assertTrue(by_id["H4"]["met"])

        # Grading needs the manifest the receipt is bound to.
        tampered = os.path.join(self.tmp, "other-manifest.json")
        registered["decision_criteria"][1]["all_of"][0]["value"] = "0.10"
        with open(tampered, "w") as fh:
            fh.write(prereg.dump_manifest(registered))
        proc = run_script(self.repo, "scripts/grade_world.py", "--run-dir",
                          run_dir, "--prereg", tampered, check=False)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("does not match the sha256 in the run receipt",
                      proc.stderr)
        proc = run_script(self.repo, "scripts/grade_world.py", "--run-dir",
                          run_dir, "--criteria-demo", tampered, check=False)
        self.assertEqual(proc.returncode, 2)

        # No second primary attempt, and no smoke after the primary.
        for extra in ((), ("--smoke",)):
            proc = self.run_prereg(*extra)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("first complete attempt is final", proc.stderr)
        self.assertEqual(len(worldkit.fake_calls(self.log)), 720)
        self.assertEqual(sorted(os.listdir(self.results)), ["attempt-01"])

        # With the registered run recorded under the registered root, the
        # freshness check re-grades it and compares REPORT-v2.md.
        registered_root = os.path.join(self.repo, prereg.RESULTS_ROOT)
        os.makedirs(os.path.dirname(registered_root))
        shutil.copytree(self.results, registered_root)
        self.assertTrue(prereg.registered_primary_complete(self.repo))
        report_path = os.path.join(self.repo, "REPORT-v2.md")
        run_script(self.repo, "scripts/world_report.py", "--run-dir",
                   os.path.join(registered_root, "attempt-01"), "--out",
                   report_path)
        with open(report_path) as fh:
            text = fh.read()
        self.assertIn("### H2:", text)
        self.assertIn("NOT MET", text)
        self.assertNotIn("FORMAT DEMONSTRATION", text)
        os.makedirs(os.path.join(self.repo, "results", "v2-mock-example"),
                    exist_ok=True)
        proc = run_script(self.repo, "scripts/check_freshness.py",
                          check=False)
        self.assertIn("fresh   REPORT-v2.md", proc.stdout)
        self.assertIn("registered run re-graded offline", proc.stdout)
        with open(report_path, "w") as fh:
            fh.write(text.replace("NOT MET", "MET"))
        proc = run_script(self.repo, "scripts/check_freshness.py",
                          check=False)
        self.assertIn("STALE   REPORT-v2.md", proc.stdout)

    def test_aborted_attempt_is_kept_and_disclosed_by_the_next(self):
        failing, fail_log = worldkit.write_fake_claude(
            self.tmp, fail_at=5, name="failing")
        proc = self.run_prereg(fake=failing)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(len(worldkit.fake_calls(fail_log)), 5)
        self.assertEqual(os.listdir(self.results), ["attempt-01.partial"])
        partial = os.path.join(self.results, "attempt-01.partial")
        self.assertTrue(os.path.exists(os.path.join(partial,
                                                    "ABORTED.json")))
        proc = run_script(self.repo, "scripts/grade_world.py", "--run-dir",
                          partial, check=False)
        self.assertEqual(proc.returncode, 2)

        proc = self.run_prereg()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(sorted(os.listdir(self.results)),
                         ["attempt-01.partial", "attempt-02"])
        with open(os.path.join(self.results, "attempt-02",
                               "receipt.json")) as fh:
            binding = json.load(fh)["preregistration"]
        self.assertEqual(binding["attempt"], 2)
        self.assertEqual(
            [(a["directory"], a["state"])
             for a in binding["earlier_attempts"]],
            [("attempt-01.partial", "aborted")])
        self.assertTrue(binding["earlier_attempts"][0]["receipt_sha256"])
        report_path = os.path.join(self.tmp, "r.md")
        run_script(self.repo, "scripts/world_report.py", "--run-dir",
                   os.path.join(self.results, "attempt-02"), "--out",
                   report_path)
        with open(report_path) as fh:
            self.assertIn("attempt-01.partial (aborted)", fh.read())


if __name__ == "__main__":
    unittest.main()
