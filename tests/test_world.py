"""v2 world-state grading: the CRM simulator, the runner, and the grader.

The grader tests are mutation tests: start from a run whose outcome is
known, break exactly one thing (in the CRM's behavior, in a persisted
artifact, or in the self-report log), and check the grade does the right
thing - counts a failure, ignores the lie, or refuses to score.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import worldkit  # noqa: E402
from worldkit import (ARMS, OracleBackend, ParseFailEvery,  # noqa: E402
                      RaisesOnNthCall, do_run, edit_decisions, edit_world,
                      reseal, write_dataset)

from harness import (integrity, metrics, runner, world,  # noqa: E402
                     world_grade, world_report, world_runner)
from harness.backends import BackendError, MockBackend  # noqa: E402
from harness.integrity import IntegrityError  # noqa: E402
from harness.world import CRMError, CRMWorld  # noqa: E402


class TmpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.data = write_dataset(self.tmp)
        self.dataset = world_runner.load_dataset(self.data)
        self.ids = [r["id"] for r in self.dataset]

    def grade(self, run_dir, data=None):
        return world_grade.grade_run(run_dir, data or self.data)


# ------------------------------------------------------------ CRM world

class TestCRMWorld(TmpCase):
    def new_crm(self):
        crm = CRMWorld.create(os.path.join(self.tmp, "w.sqlite"),
                              plan_sha256="p" * 64,
                              dataset_sha256="d" * 64,
                              receipt_sha256="r" * 64)
        self.addCleanup(crm.close)
        return crm

    def state(self, crm, world_id, lead_id):
        conn = crm._conn
        tier = conn.execute(
            "SELECT tier FROM crm_leads WHERE world_id=? AND lead_id=?",
            (world_id, lead_id)).fetchone()[0]
        queues = [r[0] for r in conn.execute(
            "SELECT queue FROM queue_membership WHERE world_id=? AND "
            "lead_id=?", (world_id, lead_id))]
        events = conn.execute(
            "SELECT COUNT(*) FROM events WHERE world_id=? AND lead_id=?",
            (world_id, lead_id)).fetchone()[0]
        return tier, queues, events

    def test_apply_records_tier_queue_and_receipt_together(self):
        crm = self.new_crm()
        handle = crm.open_world("treatment", 0, ["A", "B"])
        self.assertEqual(self.state(crm, "treatment/r0", "A"),
                         (None, ["unrouted"], 0))
        receipt = handle.apply_qualification("treatment/r0/A", "A",
                                             "team", "sales_assist")
        self.assertEqual(self.state(crm, "treatment/r0", "A"),
                         ("team", ["sales_assist"], 1))
        self.assertEqual(len(receipt), 64)
        # The other lead is untouched.
        self.assertEqual(self.state(crm, "treatment/r0", "B"),
                         (None, ["unrouted"], 0))

    def test_invalid_route_or_tier_refused_without_any_effect(self):
        crm = self.new_crm()
        handle = crm.open_world("treatment", 0, ["A"])
        for tier, route in (("team", "vip_queue"), ("whale", "sales"),
                            ("team", "unrouted")):
            with self.assertRaises(CRMError):
                handle.apply_qualification("treatment/r0/A", "A", tier,
                                           route)
        self.assertEqual(self.state(crm, "treatment/r0", "A"),
                         (None, ["unrouted"], 0))

    def test_unknown_lead_refused(self):
        crm = self.new_crm()
        handle = crm.open_world("treatment", 0, ["A"])
        with self.assertRaises(CRMError):
            handle.apply_qualification("treatment/r0/Z", "Z", "team",
                                       "sales")
        self.assertEqual(
            crm._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
            0)

    def test_second_outcome_for_same_lead_refused(self):
        crm = self.new_crm()
        handle = crm.open_world("treatment", 0, ["A", "B"])
        handle.apply_qualification("treatment/r0/A", "A", "team", "sales")
        with self.assertRaises(CRMError):
            handle.apply_qualification("treatment/r0/A", "A", "enterprise",
                                       "sales")
        with self.assertRaises(CRMError):
            handle.record_rejection("treatment/r0/A", "A", "parse_failure")
        handle.record_rejection("treatment/r0/B", "B", "parse_failure")
        with self.assertRaises(CRMError):
            handle.apply_qualification("treatment/r0/B", "B", "team",
                                       "sales")
        self.assertEqual(self.state(crm, "treatment/r0", "A"),
                         ("team", ["sales"], 1))
        self.assertEqual(self.state(crm, "treatment/r0", "B"),
                         (None, ["unrouted"], 1))

    def test_trial_from_another_arm_or_run_refused(self):
        crm = self.new_crm()
        handle = crm.open_world("treatment", 0, ["A"])
        for foreign in ("placebo/r0/A", "treatment/r1/A", "baseline/r0/A"):
            with self.assertRaises(CRMError):
                handle.apply_qualification(foreign, "A", "team", "sales")
        self.assertEqual(self.state(crm, "treatment/r0", "A"),
                         (None, ["unrouted"], 0))

    def test_one_world_open_at_a_time_and_closed_world_is_frozen(self):
        crm = self.new_crm()
        first = crm.open_world("treatment", 0, ["A"])
        with self.assertRaises(CRMError):
            crm.open_world("placebo", 0, ["A"])
        first.close()
        second = crm.open_world("placebo", 0, ["A"])
        with self.assertRaises(CRMError):  # stale handle, other arm's world
            first.apply_qualification("treatment/r0/A", "A", "team",
                                      "sales")
        second.apply_qualification("placebo/r0/A", "A", "team", "sales")
        # Writing in the placebo world did not touch the treatment world.
        self.assertEqual(self.state(crm, "treatment/r0", "A"),
                         (None, ["unrouted"], 0))
        second.close()
        with self.assertRaises(CRMError):  # same (arm, run) cannot reseed
            crm.open_world("placebo", 0, ["A"])

    def test_failed_write_rolls_back_everything(self):
        crm = self.new_crm()
        handle = crm.open_world("treatment", 0, ["A"])

        def boom(*args, **kwargs):
            raise RuntimeError("disk full")

        handle._append_event = boom
        with self.assertRaises(RuntimeError):
            handle.apply_qualification("treatment/r0/A", "A", "team",
                                       "sales")
        # Tier and queue were written inside the transaction, then undone.
        self.assertEqual(self.state(crm, "treatment/r0", "A"),
                         (None, ["unrouted"], 0))

    def test_seal_needs_closed_worlds_and_blocks_new_ones(self):
        crm = self.new_crm()
        handle = crm.open_world("treatment", 0, ["A"])
        with self.assertRaises(CRMError):
            crm.seal()
        handle.close()
        crm.seal()
        with self.assertRaises(CRMError):
            CRMWorld.create(os.path.join(self.tmp, "w.sqlite"), "p", "d",
                            "r")  # an existing world is never reused

    def test_receipts_form_a_chain(self):
        crm = self.new_crm()
        handle = crm.open_world("treatment", 0, ["A", "B"])
        r1 = handle.apply_qualification("treatment/r0/A", "A", "team",
                                        "sales")
        r2 = handle.record_rejection("treatment/r0/B", "B", "parse_failure")
        handle.close()
        crm.seal()
        snap = world.read_snapshot(os.path.join(self.tmp, "w.sqlite"))
        genesis = world.chain_genesis("p" * 64, "r" * 64)
        self.assertEqual(world.event_receipt(genesis, snap["events"][0]), r1)
        self.assertEqual(world.event_receipt(r1, snap["events"][1]), r2)
        self.assertEqual(snap["meta"]["event_chain_head"], r2)


# --------------------------------------------------------------- runner

class _SpyBackend(MockBackend):
    def __init__(self):
        super().__init__(seed=11)
        self.prompts = []

    def qualify(self, prompt, run_index=0):
        self.prompts.append(prompt)
        return super().qualify(prompt, run_index=run_index)


class TestPlanAndRunner(TmpCase):
    def test_plan_inventory_and_placebo_mapping(self):
        plan = world_runner.build_plan(self.ids, "h" * 64, ARMS, 3, 11)
        trials = plan["trials"]
        self.assertEqual(len(trials), 3 * 3 * 12)
        self.assertEqual(plan["header"]["n_model_calls"], 2 * 3 * 12)
        self.assertEqual(len({t["trial_id"] for t in trials}), len(trials))
        for t in trials:
            if t["arm"] == "placebo":
                self.assertNotEqual(t["shown_lead_id"], t["lead_id"])
            else:
                self.assertEqual(t["shown_lead_id"], t["lead_id"])
        again = world_runner.build_plan(self.ids, "h" * 64, ARMS, 3, 11)
        self.assertEqual(world_runner.plan_sha256(plan),
                         world_runner.plan_sha256(again))
        other = world_runner.build_plan(self.ids, "h" * 64, ARMS, 3, 12)
        self.assertNotEqual(world_runner.plan_sha256(plan),
                            world_runner.plan_sha256(other))

    def test_runner_view_has_no_truth_and_prompts_never_show_it(self):
        view = world_runner.model_facing(self.dataset)
        for lead in view:
            self.assertEqual(sorted(lead),
                             ["company", "contact", "id", "signals"])
        spy = _SpyBackend()
        do_run(self.tmp, self.data, backend=spy)
        self.assertEqual(len(spy.prompts), 2 * 2 * 12)
        reasons = {r["truth"]["reason"] for r in self.dataset}
        for prompt in spy.prompts:
            self.assertNotIn("truth", prompt)
            for reason in reasons:
                self.assertNotIn(reason, prompt)

    def test_log_and_world_carry_no_truth_labels(self):
        run_dir = do_run(self.tmp, self.data)
        rows = integrity.load_jsonl(os.path.join(run_dir,
                                                 "decisions.jsonl"))
        for row in rows:
            self.assertFalse([k for k in row if "true" in k or
                              k in ("truth", "tricky", "correct")])
        with open(os.path.join(run_dir, "plan.json")) as fh:
            self.assertNotIn("truth", fh.read())
        snap = world.read_snapshot(os.path.join(run_dir, "world.sqlite"))
        self.assertEqual(sorted(snap), ["events", "leads", "meta", "queues",
                                        "worlds"])

    def test_complete_run_is_sealed_and_matches_v1_arithmetic(self):
        run_dir = do_run(self.tmp, self.data, runs=2, seed=11)
        self.assertEqual(sorted(os.listdir(run_dir)),
                         ["decisions.jsonl", "manifest.json", "plan.json",
                          "receipt.json", "world.sqlite"])
        self.assertFalse(os.path.exists(run_dir + ".partial"))
        for name in os.listdir(run_dir):
            self.assertFalse(os.access(os.path.join(run_dir, name),
                                       os.W_OK) and os.getuid() != 0)
        grade = self.grade(run_dir)
        # Cross-check against the v1 runner + v1 metrics on the same
        # leads, seed and mock backend: with a faithful CRM and no parse
        # failures, effect accuracy must equal v1's answer accuracy.
        legacy_out = os.path.join(self.tmp, "legacy.jsonl")
        runner.run_all(runner.load_leads(self.data), MockBackend(seed=11),
                       ARMS, runs=2, seed=11, out_path=legacy_out)
        legacy = metrics.summarize(legacy_out)
        for arm in ARMS:
            for field in ("tier", "route"):
                self.assertEqual(
                    grade["arms"][arm][f"{field}_effect"]["correct"],
                    legacy[arm][f"{field}_accuracy"]["correct"])
                self.assertEqual(
                    grade["arms"][arm][f"{field}_effect"]["n"], 24)

    def test_completed_run_is_never_overwritten(self):
        run_dir = do_run(self.tmp, self.data)
        before = worldkit.dir_digest(run_dir)
        with self.assertRaises(world_runner.RunDirError):
            do_run(self.tmp, self.data)
        self.assertEqual(worldkit.dir_digest(run_dir), before)
        self.assertFalse(os.path.exists(run_dir + ".partial"))

    def test_cli_failure_stops_at_once_and_keeps_partial(self):
        good = do_run(self.tmp, self.data, name="good")
        before = worldkit.dir_digest(good)
        backend = RaisesOnNthCall(5)
        with self.assertRaises(BackendError):
            do_run(self.tmp, self.data, name="bad", backend=backend)
        self.assertEqual(backend.calls, 5)  # no retry, no further calls
        bad = os.path.join(self.tmp, "bad")
        self.assertFalse(os.path.exists(bad))  # nothing poses as complete
        partial = bad + ".partial"
        self.assertEqual(sorted(os.listdir(partial)),
                         ["ABORTED.json", "decisions.jsonl", "plan.json",
                          "receipt.json", "world.sqlite"])
        with open(os.path.join(partial, "ABORTED.json")) as fh:
            aborted = json.load(fh)
        self.assertEqual(aborted["decisions_logged"], 4)
        self.assertEqual(aborted["error_type"], "BackendError")
        rows = integrity.load_jsonl(os.path.join(partial,
                                                 "decisions.jsonl"))
        self.assertEqual(len(rows), 4)  # everything before the failure
        # A partial run is not gradeable, under either name.
        with self.assertRaises(IntegrityError):
            self.grade(partial)
        shutil.copytree(partial, bad)
        with self.assertRaises(IntegrityError):
            self.grade(bad)
        shutil.rmtree(bad)
        # The partial is evidence: the same run dir cannot be reused...
        with self.assertRaises(world_runner.RunDirError):
            do_run(self.tmp, self.data, name="bad")
        self.assertEqual(len(integrity.load_jsonl(
            os.path.join(partial, "decisions.jsonl"))), 4)
        # ...and the earlier complete run is untouched and still grades.
        self.assertEqual(worldkit.dir_digest(good), before)
        self.grade(good)

    def test_partial_world_even_with_forged_manifest_is_refused(self):
        with self.assertRaises(BackendError):
            do_run(self.tmp, self.data, name="bad",
                   backend=RaisesOnNthCall(30))
        partial = os.path.join(self.tmp, "bad.partial")
        forged = os.path.join(self.tmp, "forged")
        shutil.copytree(partial, forged)
        os.remove(os.path.join(forged, "ABORTED.json"))
        good = do_run(self.tmp, self.data, name="good")
        shutil.copy(os.path.join(good, "manifest.json"),
                    os.path.join(forged, "manifest.json"))
        reseal(forged)
        with self.assertRaises(IntegrityError) as ctx:
            self.grade(forged)
        self.assertIn("not sealed", str(ctx.exception))


class TestParseFailures(TmpCase):
    def test_all_unparseable_is_zero_over_full_denominator(self):
        run_dir = do_run(self.tmp, self.data, arms=["treatment"],
                         backend=ParseFailEvery(1))
        arm = self.grade(run_dir)["arms"]["treatment"]
        self.assertEqual(arm["planned_trials"], 24)
        self.assertEqual(arm["tier_effect"]["correct"], 0)
        self.assertEqual(arm["tier_effect"]["n"], 24)
        self.assertEqual(arm["route_effect"]["n"], 24)
        self.assertEqual(arm["effect_status"]["rejected"], 24)
        self.assertEqual(arm["effect_status"]["applied"], 0)
        self.assertEqual(arm["calibration"]["n"], 0)
        self.assertEqual(arm["calibration"]["n_without_confidence"], 24)

    def test_some_unparseable_stay_in_denominator_as_failures(self):
        clean = self.grade(do_run(self.tmp, self.data, name="clean",
                                  arms=["treatment"],
                                  backend=OracleBackend(self.dataset)))
        self.assertEqual(clean["arms"]["treatment"]["tier_effect"]["correct"],
                         24)

        class OracleWithGaps(OracleBackend):
            def qualify(inner, prompt, run_index=0):
                resp = super().qualify(prompt, run_index=run_index)
                if inner.calls % 4 == 0:
                    resp.call, resp.error = None, "parse: no JSON object"
                    resp.raw_text = "sorry"
                return resp

        run_dir = do_run(self.tmp, self.data, name="gaps",
                         arms=["treatment"],
                         backend=OracleWithGaps(self.dataset))
        arm = self.grade(run_dir)["arms"]["treatment"]
        # 6 of 24 answers were unparseable. v1 would report 18/18; the
        # world grade reports 18/24.
        self.assertEqual(arm["tier_effect"]["correct"], 18)
        self.assertEqual(arm["tier_effect"]["n"], 24)
        self.assertEqual(arm["route_effect"]["correct"], 18)
        self.assertEqual(arm["route_effect"]["n"], 24)
        self.assertEqual(sum(d["n"] for d in
                             arm["tier_effect"]["by_segment"].values()), 24)
        self.assertEqual(arm["effect_status"]["rejected"], 6)
        self.assertEqual(arm["calibration"]["n"], 18)
        self.assertEqual(arm["calibration"]["n_without_confidence"], 6)
        self.assertIn({"true": self.dataset[3]["truth"]["tier"],
                       "observed": world_grade.NO_TIER},
                      [{"true": c["true"], "observed": c["observed"]}
                       for c in arm["tier_confusion"]])


# ------------------------------------------- effects: the CRM misbehaves

class _Port:
    """Base for faulty CRM ports wrapped around a real WorldHandle."""

    def __init__(self, handle, targets):
        self.handle = handle
        self.targets = targets

    def record_rejection(self, *args):
        return self.handle.record_rejection(*args)

    def apply_qualification(self, trial_id, lead_id, tier, route):
        if lead_id in self.targets:
            return self.faulty(trial_id, lead_id, tier, route)
        return self.handle.apply_qualification(trial_id, lead_id, tier,
                                               route)


class DropsDispatch(_Port):
    def faulty(self, trial_id, lead_id, tier, route):
        return "0" * 64  # "success", but nothing was written


class WrongQueue(_Port):
    def faulty(self, trial_id, lead_id, tier, route):
        other = [r for r in ("self_serve", "sales_assist", "sales")
                 if r != route][0]
        return self.handle.apply_qualification(trial_id, lead_id, tier,
                                               other)


class LosesTierUpdate(_Port):
    def faulty(self, trial_id, lead_id, tier, route):
        receipt = self.handle.apply_qualification(trial_id, lead_id, tier,
                                                  route)
        self.handle._crm._conn.execute(
            "UPDATE crm_leads SET tier = NULL WHERE world_id = ? AND "
            "lead_id = ?", (self.handle.world_id, lead_id))
        return receipt


class StateWithoutReceipt(_Port):
    def faulty(self, trial_id, lead_id, tier, route):
        conn = self.handle._crm._conn
        conn.execute("UPDATE crm_leads SET tier = ? WHERE world_id = ? "
                     "AND lead_id = ?", (tier, self.handle.world_id,
                                         lead_id))
        conn.execute("UPDATE queue_membership SET queue = ? WHERE "
                     "world_id = ? AND lead_id = ?",
                     (route, self.handle.world_id, lead_id))
        return "0" * 64


class TestEffectGrading(TmpCase):
    """The model (an oracle) answers every lead correctly and the log
    says so. Whether the grade agrees depends on what reached the CRM."""

    def run_with(self, port_cls, targets, name):
        return do_run(
            self.tmp, self.data, name=name, arms=["treatment"],
            backend=OracleBackend(self.dataset),
            port_wrapper=(lambda h: port_cls(h, targets)) if port_cls
            else None)

    def arm(self, run_dir):
        grade = self.grade(run_dir)
        return grade["arms"]["treatment"], grade

    def assert_log_claims_all_correct(self, run_dir):
        truth = {r["id"]: r["truth"] for r in self.dataset}
        rows = integrity.load_jsonl(os.path.join(run_dir,
                                                 "decisions.jsonl"))
        self.assertEqual(len(rows), 24)
        for row in rows:
            self.assertTrue(row["parse_ok"])
            self.assertEqual(row["claimed_tier"],
                             truth[row["lead_id"]]["tier"])
            self.assertEqual(row["claimed_route"],
                             truth[row["lead_id"]]["route"])

    def test_faithful_crm_scores_everything(self):
        arm, grade = self.arm(self.run_with(None, set(), "ok"))
        self.assertEqual(arm["tier_effect"]["correct"], 24)
        self.assertEqual(arm["route_effect"]["correct"], 24)
        self.assertEqual(arm["effect_status"]["applied"], 24)
        self.assertEqual(
            grade["self_report_diagnostics"]["claimed_but_not_delivered"],
            0)

    def test_dropped_dispatch_fails_although_log_says_right(self):
        targets = set(self.ids[:3])
        run_dir = self.run_with(DropsDispatch, targets, "drop")
        self.assert_log_claims_all_correct(run_dir)
        arm, grade = self.arm(run_dir)
        self.assertEqual(arm["tier_effect"]["correct"], 24 - 6)
        self.assertEqual(arm["route_effect"]["correct"], 24 - 6)
        self.assertEqual(arm["tier_effect"]["n"], 24)
        self.assertEqual(arm["effect_status"]["no_effect"], 6)
        self.assertEqual(
            grade["self_report_diagnostics"]["claimed_but_not_delivered"],
            6)

    def test_wrong_queue_fails_route_only(self):
        targets = set(self.ids[:4])
        run_dir = self.run_with(WrongQueue, targets, "queue")
        self.assert_log_claims_all_correct(run_dir)
        arm, grade = self.arm(run_dir)
        self.assertEqual(arm["tier_effect"]["correct"], 24)
        self.assertEqual(arm["route_effect"]["correct"], 24 - 8)
        self.assertEqual(arm["both_effects"]["correct"], 24 - 8)
        self.assertEqual(
            grade["self_report_diagnostics"]["delivered_differs_from_claim"],
            8)

    def test_missing_tier_update_fails_tier(self):
        targets = set(self.ids[:2])
        run_dir = self.run_with(LosesTierUpdate, targets, "tier")
        self.assert_log_claims_all_correct(run_dir)
        arm, _ = self.arm(run_dir)
        self.assertEqual(arm["tier_effect"]["correct"], 24 - 4)
        self.assertEqual(arm["route_effect"]["correct"], 24)
        self.assertEqual(arm["effect_status"]["inconsistent"], 4)

    def test_state_without_dispatch_receipt_does_not_count(self):
        targets = set(self.ids[:5])
        run_dir = self.run_with(StateWithoutReceipt, targets, "norcpt")
        self.assert_log_claims_all_correct(run_dir)
        arm, _ = self.arm(run_dir)
        self.assertEqual(arm["tier_effect"]["correct"], 24 - 10)
        self.assertEqual(arm["route_effect"]["correct"], 24 - 10)
        self.assertEqual(arm["effect_status"]["inconsistent"], 10)

    def test_total_noop_crm_scores_zero(self):
        run_dir = self.run_with(DropsDispatch, set(self.ids), "noop")
        self.assert_log_claims_all_correct(run_dir)
        arm, _ = self.arm(run_dir)
        self.assertEqual(arm["tier_effect"]["correct"], 0)
        self.assertEqual(arm["route_effect"]["correct"], 0)
        self.assertEqual(arm["tier_effect"]["n"], 24)
        self.assertEqual(arm["effect_status"]["no_effect"], 24)


# ------------------------------------- the log and labels cannot buy score

class TestSelfReportCannotImproveScore(TmpCase):
    def effect_view(self, grade):
        return {arm: {k: s[k] for k in
                      ("tier_effect", "route_effect", "both_effects",
                       "effect_status", "per_lead", "tier_confusion")}
                for arm, s in grade["arms"].items()}

    def test_tampered_log_does_not_change_effect_score(self):
        run_dir = do_run(self.tmp, self.data)
        before = self.grade(run_dir)
        self.assertLess(before["arms"]["placebo"]["tier_effect"]["correct"],
                        24)
        truth = {r["id"]: r["truth"] for r in self.dataset}

        def lie(rows):
            for row in rows:
                t = truth[row["lead_id"]]
                row.update(claimed_tier=t["tier"], claimed_route=t["route"],
                           parse_ok=True, error=None, true_tier=t["tier"],
                           true_route=t["route"], pred_tier=t["tier"],
                           pred_route=t["route"], correct=True,
                           reason="verified correct, routed successfully")
            return rows

        # Without redoing the hashes the edit is simply refused.
        edit_decisions(run_dir, lie, resealed=False)
        with self.assertRaises(IntegrityError):
            self.grade(run_dir)
        # With every hash redone, the lie is read and changes nothing
        # about what the world shows.
        reseal(run_dir)
        after = self.grade(run_dir)
        self.assertEqual(self.effect_view(after), self.effect_view(before))
        self.assertGreater(
            after["self_report_diagnostics"]["delivered_differs_from_claim"],
            0)

    def test_dropping_failures_from_the_log_is_refused(self):
        run_dir = do_run(self.tmp, self.data, arms=["treatment"],
                         backend=ParseFailEvery(3))
        self.assertEqual(
            self.grade(run_dir)["arms"]["treatment"]["effect_status"]
            ["rejected"], 8)
        edit_decisions(run_dir,
                       lambda rows: [r for r in rows if r["parse_ok"]])
        with self.assertRaises(IntegrityError) as ctx:
            self.grade(run_dir)
        self.assertIn("decisions log inventory", str(ctx.exception))

    def test_duplicate_and_extra_log_rows_are_refused(self):
        for label, fn in (
                ("dup", lambda rows: rows + [rows[0]]),
                ("extra", lambda rows: rows + [dict(
                    rows[0], trial_id="treatment/r9/L9999")])):
            run_dir = do_run(self.tmp, self.data, name=label)
            edit_decisions(run_dir, fn)
            with self.assertRaises(IntegrityError):
                self.grade(run_dir)

    def test_labels_handed_to_the_runner_are_ignored(self):
        honest = self.grade(do_run(self.tmp, self.data, name="honest"))
        # Hand the runner leads whose "truth" agrees with whatever a
        # qualifier might say; it must make no difference, because the
        # runner drops labels and the grader reads the dataset file.
        rigged = []
        for row in self.dataset:
            row = json.loads(json.dumps(row))
            row["truth"] = {"tier": "enterprise", "route": "sales",
                            "reason": "rigged"}
            row["tricky"] = not row["tricky"]
            rigged.append(row)
        dishonest = self.grade(do_run(self.tmp, self.data, name="rigged",
                                      leads=rigged))
        self.assertEqual(self.effect_view(dishonest),
                         self.effect_view(honest))

    def test_relabelled_dataset_is_a_hash_mismatch(self):
        run_dir = do_run(self.tmp, self.data)
        relabelled = os.path.join(self.tmp, "relabelled.jsonl")
        with open(relabelled, "w", encoding="utf-8") as fh:
            for row in self.dataset:
                row = dict(row, truth={"tier": "team",
                                       "route": "sales_assist",
                                       "reason": "x"})
                fh.write(json.dumps(row, sort_keys=True) + "\n")
        with self.assertRaises(IntegrityError) as ctx:
            self.grade(run_dir, data=relabelled)
        self.assertIn("dataset hash mismatch", str(ctx.exception))


# ------------------------------------------------- persisted world edits

class TestWorldIntegrity(TmpCase):
    def setUp(self):
        super().setUp()
        self.run_dir = do_run(self.tmp, self.data)
        self.baseline_grade = self.grade(self.run_dir)

    def refused(self, needle=None):
        with self.assertRaises(IntegrityError) as ctx:
            self.grade(self.run_dir)
        if needle:
            self.assertIn(needle, str(ctx.exception))

    def wrong_lead(self, arm="placebo"):
        """A (world, lead, truth) the mock got wrong in the given arm."""
        truth = {r["id"]: r["truth"] for r in self.dataset}
        snap = world.read_snapshot(os.path.join(self.run_dir,
                                                "world.sqlite"))
        for row in snap["leads"]:
            if (row["world_id"].startswith(arm)
                    and row["tier"] != truth[row["lead_id"]]["tier"]):
                return row["world_id"], row["lead_id"], truth[row["lead_id"]]
        self.fail("no wrong lead to work with")

    def test_any_edit_without_resealing_is_refused(self):
        world_id, lead_id, truth = self.wrong_lead()
        edit_world(self.run_dir, [
            ("UPDATE crm_leads SET tier = ? WHERE world_id = ? AND "
             "lead_id = ?", (truth["tier"], world_id, lead_id))],
            resealed=False)
        self.refused("world.sqlite does not match its sealed sha256")

    def test_fixing_a_tier_after_the_fact_does_not_score(self):
        world_id, lead_id, truth = self.wrong_lead()
        edit_world(self.run_dir, [
            ("UPDATE crm_leads SET tier = ? WHERE world_id = ? AND "
             "lead_id = ?", (truth["tier"], world_id, lead_id))])
        after = self.grade(self.run_dir)
        arm = world_id.split("/")[0]
        # State no longer agrees with its dispatch receipt: still wrong.
        self.assertEqual(after["arms"][arm]["tier_effect"]["correct"],
                         self.baseline_grade["arms"][arm]["tier_effect"]
                         ["correct"])
        self.assertEqual(after["arms"][arm]["effect_status"]
                         ["inconsistent"], 1)

    def test_fixing_the_event_too_breaks_the_receipt_chain(self):
        # (An owner who also recomputes every receipt and hash would not
        # be caught: these are consistency checks, not a security
        # boundary.)
        world_id, lead_id, truth = self.wrong_lead()
        edit_world(self.run_dir, [
            ("UPDATE crm_leads SET tier = ? WHERE world_id = ? AND "
             "lead_id = ?", (truth["tier"], world_id, lead_id)),
            ("UPDATE events SET tier = ? WHERE world_id = ? AND "
             "lead_id = ?", (truth["tier"], world_id, lead_id))])
        self.refused("receipt does not match the chain")

    def test_missing_lead_record(self):
        edit_world(self.run_dir, [
            "PRAGMA foreign_keys = OFF",
            ("DELETE FROM queue_membership WHERE world_id = ? AND "
             "lead_id = ?", ("treatment/r0", self.ids[0])),
            ("DELETE FROM crm_leads WHERE world_id = ? AND lead_id = ?",
             ("treatment/r0", self.ids[0]))])
        self.refused("lead inventory in treatment/r0")

    def test_extra_unknown_lead(self):
        edit_world(self.run_dir, [
            "INSERT INTO crm_leads VALUES ('treatment/r0', 'L9999', 'team')",
            "INSERT INTO queue_membership VALUES ('treatment/r0', 'L9999', "
            "'sales')"])
        self.refused("unknown/extra=['L9999']")

    def test_duplicate_event_for_a_trial(self):
        edit_world(self.run_dir, [
            "INSERT INTO events (seq, world_id, lead_id, trial_id, kind, "
            "tier, queue, detail, receipt) SELECT (SELECT MAX(seq) + 1 "
            "FROM events), world_id, lead_id, trial_id, kind, tier, queue, "
            "detail, 'dup' FROM events WHERE seq = 1"])
        self.refused("more than one event")

    def test_removed_event_breaks_the_chain(self):
        edit_world(self.run_dir, ["DELETE FROM events WHERE seq = 5"])
        self.refused("sequence gap")

    def test_missing_world(self):
        edit_world(self.run_dir, [
            "DELETE FROM events WHERE world_id = 'baseline/r1'",
            "DELETE FROM queue_membership WHERE world_id = 'baseline/r1'",
            "DELETE FROM crm_leads WHERE world_id = 'baseline/r1'",
            "DELETE FROM worlds WHERE world_id = 'baseline/r1'"])
        self.refused("world inventory")

    def test_extra_world(self):
        edit_world(self.run_dir, [
            "INSERT INTO worlds VALUES ('treatment/r7', 'treatment', 7, "
            "12, 'closed')"])
        self.refused("world inventory")

    def test_event_pointing_at_another_arm_is_refused(self):
        edit_world(self.run_dir, [
            "UPDATE events SET world_id = 'baseline/r0' WHERE seq = 1"])
        self.refused("cross-arm/run reference")

    def test_copying_one_arms_world_into_another_is_refused(self):
        # Overwrite the placebo world's state with the baseline world's.
        edit_world(self.run_dir, [
            "UPDATE crm_leads SET tier = (SELECT b.tier FROM crm_leads b "
            "WHERE b.world_id = 'baseline/r0' AND b.lead_id = "
            "crm_leads.lead_id) WHERE world_id = 'placebo/r0'",
            "UPDATE events SET trial_id = REPLACE(trial_id, 'placebo/r0', "
            "'baseline/r0') WHERE world_id = 'placebo/r0'"])
        self.refused()

    def test_invalid_route_in_world(self):
        edit_world(self.run_dir, [
            ("UPDATE queue_membership SET queue = 'vip_fast_track' WHERE "
             "world_id = ? AND lead_id = ?", ("treatment/r0", self.ids[0]))],
            ignore_checks=True)
        self.refused("invalid route/queue")

    def test_invalid_tier_in_world(self):
        edit_world(self.run_dir, [
            ("UPDATE crm_leads SET tier = 'whale' WHERE world_id = ? AND "
             "lead_id = ?", ("treatment/r0", self.ids[0]))],
            ignore_checks=True)
        self.refused("invalid tier")

    def test_lead_in_two_queues(self):
        edit_world(self.run_dir, [
            ("INSERT OR IGNORE INTO queue_membership VALUES (?, ?, "
             "'unrouted')", ("treatment/r0", self.ids[0]))])
        self.refused("expected exactly 1")

    def test_unsealed_world_state(self):
        edit_world(self.run_dir, [
            "UPDATE meta SET value = 'open' WHERE key = 'state'"])
        self.refused("not sealed")

    def test_world_from_a_different_plan(self):
        edit_world(self.run_dir, [
            "UPDATE meta SET value = 'x' WHERE key = 'plan_sha256'"])
        self.refused("different plan")

    def test_unexpected_table(self):
        edit_world(self.run_dir, ["CREATE TABLE notes (x TEXT)"])
        self.refused("unexpected world schema")

    def test_corrupt_database_file(self):
        worldkit.make_writable(self.run_dir)
        path = os.path.join(self.run_dir, "world.sqlite")
        with open(path, "r+b") as fh:
            fh.truncate(1500)
        self.refused("world.sqlite does not match")
        reseal(self.run_dir)
        self.refused()
        with open(path, "wb") as fh:
            fh.write(b"this is not a database at all" * 50)
        reseal(self.run_dir)
        self.refused()

    def test_missing_artifacts(self):
        for name in ("world.sqlite", "plan.json", "decisions.jsonl",
                     "receipt.json", "manifest.json"):
            copy = os.path.join(self.tmp, "copy-" + name)
            shutil.copytree(self.run_dir, copy)
            worldkit.make_writable(copy)
            os.remove(os.path.join(copy, name))
            with self.assertRaises(IntegrityError):
                self.grade(copy)

    def test_manifest_edit_breaks_its_seal(self):
        worldkit.make_writable(self.run_dir)
        path = os.path.join(self.run_dir, "manifest.json")
        with open(path) as fh:
            manifest = json.load(fh)
        manifest["completed_at_utc"] = "2031-01-01T00:00:00Z"
        with open(path, "w") as fh:
            json.dump(manifest, fh)
        self.refused("manifest seal")

    def test_plan_with_trials_removed_is_refused(self):
        worldkit.make_writable(self.run_dir)
        path = os.path.join(self.run_dir, "plan.json")
        plan = world_runner.load_plan(path)
        plan["trials"] = [t for t in plan["trials"]
                          if t["lead_id"] != self.ids[0]]
        plan["header"]["n_trials"] = len(plan["trials"])
        with open(path, "w") as fh:
            fh.write(world_runner.dump_plan(plan))
        reseal(self.run_dir)
        self.refused()
        # Even a plan internally consistent with a smaller design fails:
        # the world, receipt and manifest were sealed for the real one.
        dataset_ids = self.ids[1:]
        smaller = world_runner.build_plan(
            dataset_ids, plan["header"]["dataset_sha256"], ARMS, 2, 11)
        with open(path, "w") as fh:
            fh.write(world_runner.dump_plan(smaller))
        reseal(self.run_dir)
        self.refused()

    def test_leftover_journal_means_unclean_world(self):
        with open(os.path.join(self.run_dir, "world.sqlite-journal"),
                  "w") as fh:
            fh.write("x")
        self.refused("not closed cleanly")


# ------------------------------------------------- arithmetic and report

class TestComparisonsAndCriteria(unittest.TestCase):
    @staticmethod
    def arm(per_lead):
        tier = sum(v[0] for v in per_lead.values())
        route = sum(v[1] for v in per_lead.values())
        n = sum(v[2] for v in per_lead.values())
        return {"per_lead": per_lead, "planned_trials": n,
                "tier_effect": {"correct": tier, "n": n},
                "route_effect": {"correct": route, "n": n},
                "effect_status": {"applied": n, "rejected": 0,
                                  "no_effect": 0, "inconsistent": 0}}

    def test_paired_difference_is_per_lead(self):
        a = self.arm({"L1": [3, 3, 3], "L2": [1, 0, 3], "L3": [0, 3, 3]})
        b = self.arm({"L1": [3, 0, 3], "L2": [2, 0, 3], "L3": [0, 3, 3]})
        cmp_tier = world_grade.paired_comparison(a, b, "a", "b", "tier")
        self.assertEqual(cmp_tier["n_leads"], 3)
        self.assertEqual((cmp_tier["leads_a_better"],
                          cmp_tier["leads_b_better"],
                          cmp_tier["leads_tied"]), (0, 1, 2))
        # d = (0, -1/3, 0) -> mean -1/9
        self.assertAlmostEqual(cmp_tier["mean_per_lead_difference"], -1 / 9)
        self.assertEqual(cmp_tier["lead_run_delta"], -1)
        cmp_route = world_grade.paired_comparison(a, b, "a", "b", "route")
        self.assertEqual((cmp_route["leads_a_better"],
                          cmp_route["leads_b_better"],
                          cmp_route["leads_tied"]), (1, 0, 2))
        self.assertAlmostEqual(cmp_route["mean_per_lead_difference"], 1 / 3)

    def test_paired_comparison_needs_the_same_leads(self):
        a = self.arm({"L1": [3, 3, 3]})
        b = self.arm({"L2": [3, 3, 3]})
        with self.assertRaises(IntegrityError):
            world_grade.paired_comparison(a, b, "a", "b", "tier")

    def test_criteria_use_exact_arithmetic_at_the_boundary(self):
        def arms(treat_route):
            return {
                "treatment": self.arm({f"L{i}": [3, 3 if i < treat_route
                                                 else 0, 3]
                                       for i in range(120)}),
                "baseline": self.arm({f"L{i}": [3, 3 if i < 100 else 0, 3]
                                      for i in range(120)})}
        crit = [{"id": "X", "label": "x", "if_met": "y", "if_not_met": "n",
                 "all_of": [{"metric": "abs_route_effect_accuracy_diff",
                             "arm": "treatment", "vs": "baseline",
                             "op": "<=", "value": "0.05"}]}]
        # 106 vs 100 leads fully right: 318/360 vs 300/360 = exactly 0.05.
        res = world_grade.evaluate_criteria(arms(106), crit)[0]
        self.assertTrue(res["met"])
        self.assertEqual(res["conditions"][0]["observed"],
                         "318/360 vs 300/360")
        self.assertFalse(
            world_grade.evaluate_criteria(arms(107), crit)[0]["met"])
        self.assertTrue(
            world_grade.evaluate_criteria(arms(94), crit)[0]["met"])
        self.assertFalse(
            world_grade.evaluate_criteria(arms(93), crit)[0]["met"])

    def test_undelivered_criterion_counts_every_non_applied_trial(self):
        arms = {"treatment": self.arm({"L1": [3, 3, 3]})}
        crit = [{"id": "H4", "label": "x", "if_met": "y", "if_not_met": "n",
                 "all_of": [{"metric": "undelivered_trials", "op": "==",
                             "value": "0"}]}]
        self.assertTrue(world_grade.evaluate_criteria(arms, crit)[0]["met"])
        arms["treatment"]["effect_status"].update(applied=2, rejected=1)
        res = world_grade.evaluate_criteria(arms, crit)[0]
        self.assertFalse(res["met"])
        self.assertEqual(res["conditions"][0]["observed"],
                         "1 of 3 planned")

    def test_criterion_on_absent_arm_is_not_evaluable(self):
        arms = {"treatment": self.arm({"L1": [3, 3, 3]})}
        crit = [{"id": "H1", "label": "x", "if_met": "y", "if_not_met": "n",
                 "all_of": [{"metric": "tier_effect_accuracy",
                             "arm": "placebo", "op": "<=",
                             "value": "0.5"}]}]
        self.assertIsNone(
            world_grade.evaluate_criteria(arms, crit)[0]["met"])


class TestWorldReport(TmpCase):
    def test_report_is_dated_from_the_artifact_and_labeled_mock(self):
        run_dir = do_run(self.tmp, self.data)
        grade = self.grade(run_dir)
        text = world_report.render(grade)
        self.assertIn(worldkit.FIXED_CLOCK, text)  # 2020, not today
        self.assertIn("MOCK", text.splitlines()[0])
        self.assertIn("MOCK BACKEND", text)
        self.assertIn("This run is not preregistered.", text)
        self.assertIn("not tamperproof", text)
        self.assertEqual(text, world_report.render(self.grade(run_dir)))
        self.assertEqual(world_grade.dump_grade(grade),
                         world_grade.dump_grade(self.grade(run_dir)))
        # Every accuracy carries its denominator.
        self.assertIn("/24 (", text)

    def test_calibration_uses_world_correctness_not_the_claim(self):
        # The oracle claims 0.9 confidence and is "right" every time, but
        # the CRM drops every dispatch: calibration must see 0% accuracy.
        run_dir = do_run(
            self.tmp, self.data, arms=["treatment"],
            backend=OracleBackend(self.dataset, confidence=0.9),
            port_wrapper=lambda h: DropsDispatch(h, set(self.ids)))
        cal = self.grade(run_dir)["arms"]["treatment"]["calibration"]
        self.assertEqual(cal["n"], 24)
        self.assertEqual(cal["accuracy"], 0.0)
        self.assertAlmostEqual(cal["brier"], 0.81)
        self.assertAlmostEqual(cal["ece"], 0.9)


if __name__ == "__main__":
    unittest.main()
