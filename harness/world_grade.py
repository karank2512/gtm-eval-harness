"""Offline world-state grader (v2).

Inputs, and what each is trusted for:

- the persisted CRM world database  -> what actually happened (effects)
- the dataset file                  -> truth labels (independent of the run)
- the sealed trial plan             -> which trials must exist, and only those
- the decisions log                 -> the model's self-reported confidence,
                                       for calibration ONLY

Correctness never comes from the decisions log. A trial counts as correct
only if the world shows the effect: the lead record carries the true tier,
the lead sits in the true route's queue, and a dispatch event with a valid
receipt agrees with that state. A decision that was claimed but not
applied, applied to the wrong queue, or dropped is a failure. Unparseable
answers stay in every denominator as failures.

Structural problems (wrong hashes, missing/extra/duplicate/unknown rows,
cross-world references, broken receipt chain, unsealed or aborted run)
are not graded around: the grader raises IntegrityError and produces no
score. These checks catch accidents and careless edits. They are not
tamperproof: the hashes live next to the data they describe.
"""

from __future__ import annotations

import json
import math
import os
from collections import Counter, defaultdict
from fractions import Fraction
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import integrity, world, world_runner
from .integrity import IntegrityError
from .pipeline import ROUTES, TIERS

GRADE_SCHEMA = "gtm-world-grade/1"
STATUS_APPLIED = "applied"
STATUS_REJECTED = "rejected"
STATUS_NO_EFFECT = "no_effect"
STATUS_INCONSISTENT = "inconsistent"
STATUSES = [STATUS_APPLIED, STATUS_REJECTED, STATUS_NO_EFFECT,
            STATUS_INCONSISTENT]
NO_TIER = "(no tier assigned)"


def _fail(problems: Sequence[str], what: str) -> None:
    if problems:
        shown = "; ".join(problems[:8])
        more = f" (+{len(problems) - 8} more)" if len(problems) > 8 else ""
        raise IntegrityError(f"{what}: {shown}{more}")


def _load_json(path: str, what: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            obj = json.load(fh)
    except (OSError, ValueError) as exc:
        raise IntegrityError(f"{what} is unreadable: {exc}") from exc
    if not isinstance(obj, dict):
        raise IntegrityError(f"{what} is not a JSON object")
    return obj


# ------------------------------------------------------- sealed artifacts

def verify_run_dir(run_dir: str) -> Dict[str, Any]:
    """Fail closed unless `run_dir` is a completed, unmodified run."""
    run_dir = os.path.normpath(run_dir)
    if not os.path.isdir(run_dir):
        raise IntegrityError(f"run directory missing: {run_dir}")
    if run_dir.endswith(".partial") or os.path.exists(
            os.path.join(run_dir, world_runner.ABORTED_FILE)):
        raise IntegrityError(
            f"{run_dir} is an aborted or partial run; it is not gradeable")
    manifest_path = os.path.join(run_dir, world_runner.MANIFEST_FILE)
    if not os.path.isfile(manifest_path):
        raise IntegrityError(
            f"{run_dir} has no manifest: the run did not complete")
    manifest = _load_json(manifest_path, "manifest")
    problems = []
    if manifest.get("schema") != world_runner.MANIFEST_SCHEMA:
        problems.append(f"unknown manifest schema {manifest.get('schema')!r}")
    if manifest.get("state") != "complete":
        problems.append(f"manifest state is {manifest.get('state')!r}")
    if manifest.get("grading") != world_runner.GRADING_LABEL:
        problems.append("manifest is not a v2 world-state run")
    if world_runner.seal_manifest(manifest) != manifest:
        problems.append("manifest seal does not match its contents")
    artifacts = manifest.get("artifacts")
    if (not isinstance(artifacts, dict)
            or sorted(artifacts) != sorted(world_runner.SEALED_FILES)):
        problems.append("manifest does not list exactly the sealed files")
        _fail(problems, "run manifest invalid")
    for name in world_runner.SEALED_FILES:
        path = os.path.join(run_dir, name)
        if not os.path.isfile(path):
            problems.append(f"{name} is missing")
        elif integrity.sha256_file(path) != artifacts[name]:
            problems.append(f"{name} does not match its sealed sha256")
    _fail(problems, "run artifacts invalid")
    return manifest


# ------------------------------------------------------- world validation

def validate_world(snapshot: Dict[str, Any], plan: Dict[str, Any],
                   receipt_sha256: Optional[str] = None,
                   manifest: Optional[Dict[str, Any]] = None
                   ) -> List[Dict[str, str]]:
    """Check the world's structure against the sealed plan. Returns the
    list of checks performed; raises IntegrityError on any violation."""
    header = plan["header"]
    plan_sha = world_runner.plan_sha256(plan)
    expected_leads = list(header["lead_ids"])
    expected_worlds = {world.world_id_for(arm, run): (arm, run)
                       for arm in header["arms"]
                       for run in range(header["runs"])}
    problems: List[str] = []
    checks: List[Dict[str, str]] = []

    meta = snapshot["meta"]
    if meta.get("schema_version") != world.SCHEMA_VERSION:
        problems.append("world schema version mismatch")
    if meta.get("state") != "sealed":
        problems.append(f"world state is {meta.get('state')!r}, not sealed")
    if meta.get("plan_sha256") != plan_sha:
        problems.append("world was built for a different plan")
    if meta.get("dataset_sha256") != header["dataset_sha256"]:
        problems.append("world was built for a different dataset")
    if receipt_sha256 is not None and (
            meta.get("receipt_sha256") != receipt_sha256):
        problems.append("world was built under a different run receipt")
    genesis = world.chain_genesis(plan_sha, meta.get("receipt_sha256", ""))
    if meta.get("chain_genesis") != genesis:
        problems.append("event chain genesis mismatch")
    checks.append({"check": "world metadata",
                   "detail": "sealed; bound to this plan, dataset and "
                             "run receipt"})

    # Worlds: exactly one per planned (arm, run), each closed.
    seen_worlds = [w["world_id"] for w in snapshot["worlds"]]
    missing, extra, dupes = integrity.inventory_diff(
        expected_worlds, seen_worlds)
    if missing or extra or dupes:
        problems.append(f"world inventory: missing={missing} extra={extra} "
                        f"duplicate={dupes}")
    for w in snapshot["worlds"]:
        if expected_worlds.get(w["world_id"]) != (w["arm"], w["run_index"]):
            problems.append(f"world {w['world_id']!r} has wrong arm/run")
        if w["state"] != "closed":
            problems.append(f"world {w['world_id']!r} was never closed")
        if w["seeded_leads"] != len(expected_leads):
            problems.append(f"world {w['world_id']!r} seeded with "
                            f"{w['seeded_leads']} leads")
    checks.append({"check": "arm/run worlds",
                   "detail": f"{len(expected_worlds)} isolated worlds, one "
                             "per planned arm x run, all closed"})

    # Lead roster per world: exact, no duplicates, no unknown leads.
    roster: Dict[str, List[str]] = defaultdict(list)
    tiers: Dict[Tuple[str, str], Optional[str]] = {}
    for row in snapshot["leads"]:
        roster[row["world_id"]].append(row["lead_id"])
        tiers[(row["world_id"], row["lead_id"])] = row["tier"]
        if row["tier"] is not None and row["tier"] not in TIERS:
            problems.append(f"invalid tier {row['tier']!r} on "
                            f"{row['world_id']}/{row['lead_id']}")
    for world_id in sorted(set(roster) | set(expected_worlds)):
        if world_id not in expected_worlds:
            problems.append(f"lead rows in unknown world {world_id!r}")
            continue
        missing, extra, dupes = integrity.inventory_diff(
            expected_leads, roster.get(world_id, []))
        if missing or extra or dupes:
            problems.append(
                f"lead inventory in {world_id}: missing={missing[:5]} "
                f"unknown/extra={extra[:5]} duplicate={dupes[:5]}")
    checks.append({"check": "lead inventory",
                   "detail": f"{len(expected_leads)} planned leads in "
                             f"each world; no missing, duplicate, extra "
                             f"or unknown ids "
                             f"({len(expected_leads) * len(expected_worlds)}"
                             f" lead records)"})

    # Queue membership: every lead in exactly one valid queue.
    queues: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    for row in snapshot["queues"]:
        key = (row["world_id"], row["lead_id"])
        if key not in tiers:
            problems.append(f"queue row for unknown lead {key}")
        if row["queue"] not in world.QUEUES:
            problems.append(f"invalid route/queue {row['queue']!r} for "
                            f"{key}")
        queues[key].append(row["queue"])
    for key in tiers:
        if len(queues.get(key, [])) != 1:
            problems.append(f"lead {key} is in {len(queues.get(key, []))} "
                            "queues, expected exactly 1")
    checks.append({"check": "queue membership",
                   "detail": "every lead record is in exactly one known "
                             "queue; no invalid routes"})

    # Events: contiguous, chained, in the right world, one per trial.
    prev = meta.get("chain_genesis", "")
    per_trial: Counter = Counter()
    for index, event in enumerate(snapshot["events"], start=1):
        where = f"event {event['seq']}"
        if event["seq"] != index:
            problems.append(f"{where}: sequence gap or reorder")
        if world.event_receipt(prev, event) != event["receipt"]:
            problems.append(f"{where}: receipt does not match the chain")
        prev = event["receipt"]
        key = (event["world_id"], event["lead_id"])
        if event["world_id"] not in expected_worlds:
            problems.append(f"{where}: unknown world {event['world_id']!r}")
        elif key not in tiers:
            problems.append(f"{where}: unknown lead {event['lead_id']!r}")
        if event["trial_id"] != f"{event['world_id']}/{event['lead_id']}":
            problems.append(
                f"{where}: trial {event['trial_id']!r} recorded in world "
                f"{event['world_id']!r} (cross-arm/run reference)")
        if event["kind"] == world.EVENT_APPLIED:
            if event["tier"] not in TIERS or event["queue"] not in ROUTES:
                problems.append(f"{where}: invalid tier/route in event")
        elif event["kind"] == world.EVENT_REJECTED:
            if (event["tier"] is not None or event["queue"] is not None
                    or event["detail"] not in world.REJECTION_REASONS):
                problems.append(f"{where}: malformed rejection event")
        else:
            problems.append(f"{where}: unknown kind {event['kind']!r}")
        per_trial[event["trial_id"]] += 1
    repeated = sorted(t for t, n in per_trial.items() if n > 1)
    if repeated:
        problems.append(f"more than one event for trials {repeated[:5]}")
    planned_ids = {t["trial_id"] for t in plan["trials"]}
    stray = sorted(set(per_trial) - planned_ids)
    if stray:
        problems.append(f"events for unplanned trials {stray[:5]}")
    head = prev
    if meta.get("event_chain_head") != head:
        problems.append("event chain head does not match world metadata")
    if meta.get("event_count") != str(len(snapshot["events"])):
        problems.append("event count does not match world metadata")
    if manifest is not None:
        if manifest.get("event_chain_head") != head:
            problems.append("event chain head does not match the manifest")
        counts = manifest.get("counts", {})
        if counts.get("events") != len(snapshot["events"]):
            problems.append("event count does not match the manifest")
        if counts.get("planned_trials") != header["n_trials"]:
            problems.append("manifest trial count does not match the plan")
    checks.append({"check": "event receipts",
                   "detail": f"{len(snapshot['events'])} events; receipt "
                             "chain recomputed; at most one event per "
                             "trial; no cross-arm/run references"})
    _fail(problems, "world failed integrity validation")
    return checks


# ------------------------------------------------------------ effect grade

def grade_effects(snapshot: Dict[str, Any], plan: Dict[str, Any],
                  dataset: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One graded row per PLANNED trial, from world state and dataset
    truth only. The decisions log is not an input to this function."""
    truth = {row["id"]: row for row in dataset}
    tiers = {(r["world_id"], r["lead_id"]): r["tier"]
             for r in snapshot["leads"]}
    queues = {(r["world_id"], r["lead_id"]): r["queue"]
              for r in snapshot["queues"]}
    events = {e["trial_id"]: e for e in snapshot["events"]}
    graded = []
    for trial in plan["trials"]:
        lead = truth.get(trial["lead_id"])
        if lead is None:
            raise IntegrityError(
                f"plan names lead {trial['lead_id']!r} that the dataset "
                "does not contain")
        key = (world.world_id_for(trial["arm"], trial["run_index"]),
               trial["lead_id"])
        if key not in tiers or key not in queues:
            raise IntegrityError(f"world has no record for trial "
                                 f"{trial['trial_id']!r}")
        tier, queue = tiers[key], queues[key]
        event = events.get(trial["trial_id"])
        untouched = tier is None and queue == world.UNROUTED
        applied = event is not None and event["kind"] == world.EVENT_APPLIED
        if applied and event["tier"] == tier and event["queue"] == queue:
            status = STATUS_APPLIED
        elif event is None and untouched:
            status = STATUS_NO_EFFECT
        elif (event is not None and event["kind"] == world.EVENT_REJECTED
              and untouched):
            status = STATUS_REJECTED
        else:
            status = STATUS_INCONSISTENT
        # An effect counts only when the state and its dispatch receipt
        # agree with each other AND with the truth label.
        tier_ok = (applied and event["tier"] == tier
                   and tier == lead["truth"]["tier"])
        route_ok = (applied and event["queue"] == queue
                    and queue == lead["truth"]["route"])
        graded.append({
            "trial_id": trial["trial_id"], "arm": trial["arm"],
            "run_index": trial["run_index"], "lead_id": trial["lead_id"],
            "tricky": bool(lead["tricky"]),
            "true_tier": lead["truth"]["tier"],
            "true_route": lead["truth"]["route"],
            "assigned_tier": tier, "queue": queue, "status": status,
            "tier_correct": bool(tier_ok), "route_correct": bool(route_ok),
        })
    return graded


# ----------------------------------------------------------- decisions log

def load_decisions(path: str, plan: Dict[str, Any]
                   ) -> Dict[str, Dict[str, Any]]:
    """The self-report log, keyed by trial id, with exact inventory."""
    rows = integrity.load_jsonl(path)
    ids = [r.get("trial_id") for r in rows]
    missing, extra, dupes = integrity.inventory_diff(
        [t["trial_id"] for t in plan["trials"]], ids)
    if missing or extra or dupes:
        raise IntegrityError(
            f"decisions log inventory: {len(rows)} rows for "
            f"{len(plan['trials'])} planned trials; missing={missing[:5]} "
            f"extra={extra[:5]} duplicate={dupes[:5]}")
    for row in rows:
        conf = row.get("confidence")
        if conf is not None and not (
                isinstance(conf, (int, float)) and not isinstance(conf, bool)
                and 0.0 <= conf <= 1.0):
            raise IntegrityError(
                f"decisions log: invalid confidence on {row['trial_id']}")
    return {r["trial_id"]: r for r in rows}


def self_report_diagnostics(graded: Sequence[Dict[str, Any]],
                            decisions: Dict[str, Dict[str, Any]]
                            ) -> Dict[str, Any]:
    """Where the self-report log and the world disagree. Informational:
    the world wins every disagreement, by construction."""
    claimed_not_delivered = 0
    delivered_differs = 0
    unparsed_logged = 0
    for g in graded:
        d = decisions[g["trial_id"]]
        if not d.get("parse_ok"):
            unparsed_logged += 1
            continue
        if g["status"] != STATUS_APPLIED:
            claimed_not_delivered += 1
        elif (d.get("claimed_tier") != g["assigned_tier"]
              or d.get("claimed_route") != g["queue"]):
            delivered_differs += 1
    return {"n": len(graded),
            "log_parse_failures": unparsed_logged,
            "claimed_but_not_delivered": claimed_not_delivered,
            "delivered_differs_from_claim": delivered_differs}


# ---------------------------------------------------------------- summary

def _rate(correct: int, n: int) -> Dict[str, Any]:
    return {"correct": correct, "n": n,
            "accuracy": (correct / n) if n else None}


def _accuracy(rows: Sequence[Dict[str, Any]], field: str) -> Dict[str, Any]:
    flag, seg_key = f"{field}_correct", f"true_{field}"
    out = _rate(sum(1 for r in rows if r[flag]), len(rows))
    segments: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        segments[r[seg_key]].append(r)
    out["by_segment"] = {
        seg: _rate(sum(1 for r in group if r[flag]), len(group))
        for seg, group in sorted(segments.items())}
    return out


def _confusion(rows: Sequence[Dict[str, Any]], true_key: str,
               got_key: str, none_label: str) -> List[Dict[str, Any]]:
    counts: Counter = Counter()
    for r in rows:
        counts[(r[true_key], r[got_key] or none_label)] += 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"true": t, "observed": o, "n": n} for (t, o), n in ordered]


def _calibration(rows: Sequence[Dict[str, Any]], bins: int = 5
                 ) -> Dict[str, Any]:
    """Self-reported confidence vs tier EFFECT correctness. Only trials
    that reported a confidence can be scored; the rest are counted."""
    scored = [r for r in rows if r.get("confidence") is not None]
    n = len(scored)
    out: Dict[str, Any] = {"n": n, "n_without_confidence": len(rows) - n,
                           "ece": None, "brier": None,
                           "mean_confidence": None, "accuracy": None,
                           "bins": []}
    if not n:
        return out
    hits = [1.0 if r["tier_correct"] else 0.0 for r in scored]
    confs = [float(r["confidence"]) for r in scored]
    out["brier"] = math.fsum((c - h) ** 2 for c, h in zip(confs, hits)) / n
    out["mean_confidence"] = math.fsum(confs) / n
    out["accuracy"] = sum(1 for h in hits if h) / n
    buckets: List[List[int]] = [[] for _ in range(bins)]
    for i, c in enumerate(confs):
        buckets[min(bins - 1, int(c * bins))].append(i)
    terms = []
    for b, members in enumerate(buckets):
        if not members:
            continue
        mean_conf = math.fsum(confs[i] for i in members) / len(members)
        acc = sum(1 for i in members if hits[i]) / len(members)
        terms.append(len(members) / n * abs(mean_conf - acc))
        out["bins"].append({"bin": f"{b / bins:.1f}-{(b + 1) / bins:.1f}",
                            "n": len(members), "mean_confidence": mean_conf,
                            "accuracy": acc})
    out["ece"] = math.fsum(terms)
    return out


def _stability(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Run-to-run stability of the tier actually assigned in the world
    ("no tier assigned" is its own outcome)."""
    by_lead: Dict[str, List[str]] = defaultdict(list)
    by_run: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_lead[r["lead_id"]].append(r["assigned_tier"] or NO_TIER)
        by_run[r["run_index"]].append(r)
    multi = {k: v for k, v in by_lead.items() if len(v) > 1}
    flips = [1.0 - Counter(v).most_common(1)[0][1] / len(v)
             for _, v in sorted(multi.items())]
    runs = {}
    for run_index, group in sorted(by_run.items()):
        runs[str(run_index)] = {
            "tier": _rate(sum(1 for r in group if r["tier_correct"]),
                          len(group)),
            "route": _rate(sum(1 for r in group if r["route_correct"]),
                           len(group))}
    tier_accs = [v["tier"]["accuracy"] for v in runs.values()]
    return {"leads_with_multiple_runs": len(multi),
            "leads_with_any_flip": sum(1 for f in flips if f > 0),
            "mean_per_lead_flip": (math.fsum(flips) / len(flips)
                                   if flips else None),
            "by_run": runs,
            "tier_accuracy_spread": ((max(tier_accs) - min(tier_accs))
                                     if tier_accs else None)}


def summarize_arm(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    status = Counter(r["status"] for r in rows)
    per_lead: Dict[str, List[int]] = {}
    for r in rows:
        entry = per_lead.setdefault(r["lead_id"], [0, 0, 0])
        entry[0] += int(r["tier_correct"])
        entry[1] += int(r["route_correct"])
        entry[2] += 1
    tricky = {}
    for label, flag in (("clean", False), ("tricky", True)):
        group = [r for r in rows if r["tricky"] is flag]
        tricky[label] = _rate(sum(1 for r in group if r["tier_correct"]),
                              len(group))
    return {
        "planned_trials": len(rows),
        "independent_leads": len(per_lead),
        "effect_status": {s: status.get(s, 0) for s in STATUSES},
        "tier_effect": _accuracy(rows, "tier"),
        "route_effect": _accuracy(rows, "route"),
        "both_effects": _rate(sum(1 for r in rows if r["tier_correct"]
                                  and r["route_correct"]), len(rows)),
        "tricky_gap": tricky,
        "tier_confusion": _confusion(rows, "true_tier", "assigned_tier",
                                     NO_TIER),
        "route_confusion": _confusion(rows, "true_route", "queue",
                                      world.UNROUTED),
        "calibration": _calibration(rows),
        "stability": _stability(rows),
        "per_lead": {k: v for k, v in sorted(per_lead.items())},
    }


def paired_comparison(a: Dict[str, Any], b: Dict[str, Any], name_a: str,
                      name_b: str, field: str) -> Dict[str, Any]:
    """Per-lead paired difference in effect accuracy between two arms.

    The unit is the LEAD (each lead's share of correct runs in arm A minus
    its share in arm B), because repeated runs of one lead are not
    independent cases. Descriptive only: no test, no p-value.
    """
    index = 0 if field == "tier" else 1
    leads = sorted(set(a["per_lead"]) & set(b["per_lead"]))
    if set(a["per_lead"]) != set(b["per_lead"]):
        raise IntegrityError("arms do not cover the same leads")
    diffs = []
    for lead_id in leads:
        ka, kb = a["per_lead"][lead_id], b["per_lead"][lead_id]
        diffs.append(Fraction(ka[index], ka[2]) - Fraction(kb[index], kb[2]))
    total = sum(diffs, Fraction(0))
    mean = total / len(diffs) if diffs else None
    return {
        "a": name_a, "b": name_b, "field": field,
        "n_leads": len(leads),
        "leads_a_better": sum(1 for d in diffs if d > 0),
        "leads_b_better": sum(1 for d in diffs if d < 0),
        "leads_tied": sum(1 for d in diffs if d == 0),
        "mean_per_lead_difference": float(mean) if diffs else None,
        "lead_run_delta": (a[f"{field}_effect"]["correct"]
                           - b[f"{field}_effect"]["correct"]),
        "a_lead_runs": {"correct": a[f"{field}_effect"]["correct"],
                        "n": a[f"{field}_effect"]["n"]},
        "b_lead_runs": {"correct": b[f"{field}_effect"]["correct"],
                        "n": b[f"{field}_effect"]["n"]},
    }


# --------------------------------------------------- preregistered criteria

_OPS = {"<=": lambda x, y: x <= y, ">=": lambda x, y: x >= y,
        "<": lambda x, y: x < y, ">": lambda x, y: x > y,
        "==": lambda x, y: x == y}


def _metric(arms: Dict[str, Any], cond: Dict[str, Any]
            ) -> Tuple[Fraction, str]:
    """Exact value of one criterion metric, plus how it was observed."""
    metric = cond["metric"]

    def acc(arm: str, field: str) -> Tuple[Fraction, str]:
        d = arms[arm][f"{field}_effect"]
        return Fraction(d["correct"], d["n"]), f"{d['correct']}/{d['n']}"

    if metric in ("tier_effect_accuracy", "route_effect_accuracy"):
        return acc(cond["arm"], metric.split("_")[0])
    if metric in ("tier_effect_accuracy_diff", "route_effect_accuracy_diff",
                  "abs_tier_effect_accuracy_diff",
                  "abs_route_effect_accuracy_diff"):
        field = metric.replace("abs_", "").split("_")[0]
        va, sa = acc(cond["arm"], field)
        vb, sb = acc(cond["vs"], field)
        value = va - vb
        if metric.startswith("abs_"):
            value = abs(value)
        return value, f"{sa} vs {sb}"
    if metric == "undelivered_trials":
        names = [cond["arm"]] if cond.get("arm") else sorted(arms)
        count = sum(arms[n]["planned_trials"]
                    - arms[n]["effect_status"][STATUS_APPLIED]
                    for n in names)
        total = sum(arms[n]["planned_trials"] for n in names)
        return Fraction(count), f"{count} of {total} planned"
    raise IntegrityError(f"unknown criterion metric {metric!r}")


def evaluate_criteria(arms: Dict[str, Any],
                      criteria: Sequence[Dict[str, Any]]
                      ) -> List[Dict[str, Any]]:
    """Apply prespecified descriptive criteria with exact arithmetic."""
    results = []
    for crit in criteria:
        conditions = []
        for cond in crit["all_of"]:
            needed = [cond.get("arm"), cond.get("vs")]
            if any(n and n not in arms for n in needed):
                conditions.append({"condition": cond, "observed": "n/a",
                                   "value": None, "met": None})
                continue
            value, observed = _metric(arms, cond)
            met = _OPS[cond["op"]](value, Fraction(str(cond["value"])))
            conditions.append({"condition": cond, "observed": observed,
                               "value": float(value), "met": bool(met)})
        evaluable = all(c["met"] is not None for c in conditions)
        results.append({
            "id": crit["id"], "label": crit["label"],
            "conditions": conditions,
            "met": (all(c["met"] for c in conditions) if evaluable
                    else None),
            "if_met": crit["if_met"], "if_not_met": crit["if_not_met"]})
    return results


# ------------------------------------------------------------------ grade

def grade_run(run_dir: str, data_path: str,
              prereg_manifest_path: Optional[str] = None,
              criteria_demo_path: Optional[str] = None) -> Dict[str, Any]:
    """Grade a completed run offline. Raises IntegrityError (no score)
    unless every sealed artifact, the plan, the dataset and the world all
    check out.

    prereg_manifest_path: required for a preregistered run - the manifest
        the receipt is bound to; its criteria are applied to a primary run.
    criteria_demo_path: for a run that is NOT preregistered, apply a
        manifest's criteria purely to exercise the report format.
    """
    manifest = verify_run_dir(run_dir)
    checks = [{"check": "sealed artifacts",
               "detail": "manifest complete and self-consistent; plan, "
                         "receipt, world database and decisions log match "
                         "their sealed sha256"}]
    path = lambda name: os.path.join(run_dir, name)  # noqa: E731
    plan = world_runner.load_plan(path(world_runner.PLAN_FILE))
    header = plan["header"]
    receipt = _load_json(path(world_runner.RECEIPT_FILE), "receipt")

    problems = []
    if world_runner.plan_sha256(plan) != manifest["plan_sha256"]:
        problems.append("plan does not match the manifest")
    if receipt.get("plan_sha256") != manifest["plan_sha256"]:
        problems.append("receipt is for a different plan")
    for key in ("kind", "preregistered", "started_at_utc"):
        if receipt.get(key) != manifest.get(key):
            problems.append(f"receipt and manifest disagree on {key}")
    if not isinstance(manifest.get("completed_at_utc"), str):
        problems.append("manifest has no completion time")
    _fail(problems, "run metadata inconsistent")

    # Dataset: the file given must be the one the run was planned on, and
    # the sealed plan must be exactly what that dataset + design produce.
    data_sha = integrity.sha256_file(data_path)
    if data_sha != header["dataset_sha256"] or (
            data_sha != manifest["dataset_sha256"]):
        raise IntegrityError(
            "dataset hash mismatch: this run was planned on dataset "
            f"{header['dataset_sha256'][:12]}..., the file given is "
            f"{data_sha[:12]}...")
    dataset = world_runner.load_dataset(data_path)
    try:
        expected = world_runner.build_plan(
            [r["id"] for r in dataset], data_sha, header["arms"],
            header["runs"], header["seed"], header["limit"])
    except (ValueError, TypeError, KeyError) as exc:
        raise IntegrityError(f"plan header is not a valid design: {exc}")
    if world_runner.dump_plan(expected) != world_runner.dump_plan(plan):
        raise IntegrityError(
            "sealed plan is not the trial inventory this dataset and "
            "design produce (missing, extra or altered trial identities)")
    checks.append({"check": "dataset and plan",
                   "detail": f"dataset sha256 matches; plan regenerated "
                             f"from dataset + design is identical "
                             f"({header['n_trials']} trial identities)"})

    criteria = _resolve_criteria(receipt, manifest, plan,
                                 prereg_manifest_path, criteria_demo_path)
    if receipt.get("preregistered"):
        checks.append({"check": "preregistration binding",
                       "detail": "receipt names the preregistration "
                                 "manifest by sha256 and git commit; the "
                                 "manifest given matches and pins this "
                                 "dataset and plan"})

    snapshot = world.read_snapshot(path(world_runner.WORLD_FILE))
    checks += validate_world(
        snapshot, plan,
        receipt_sha256=manifest["artifacts"][world_runner.RECEIPT_FILE],
        manifest=manifest)
    graded = grade_effects(snapshot, plan, dataset)
    if len(graded) != header["n_trials"]:
        raise IntegrityError("graded trial count does not match the plan")

    decisions = load_decisions(path(world_runner.DECISIONS_FILE), plan)
    checks.append({"check": "decisions log inventory",
                   "detail": f"{len(decisions)} rows, exactly one per "
                             "planned trial (used for self-reported "
                             "confidence only)"})
    for g in graded:
        g["confidence"] = decisions[g["trial_id"]].get("confidence")

    by_arm: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for g in graded:
        by_arm[g["arm"]].append(g)
    arms = {arm: summarize_arm(by_arm[arm]) for arm in header["arms"]}
    comparisons = []
    for a, b in (("treatment", "baseline"), ("treatment", "placebo")):
        if a in arms and b in arms:
            for field in ("tier", "route"):
                comparisons.append(
                    paired_comparison(arms[a], arms[b], a, b, field))
    if criteria is not None and criteria["applies"]:
        criteria["results"] = evaluate_criteria(arms, criteria.pop("spec"))
    elif criteria is not None:
        criteria.pop("spec", None)

    return {
        "schema": GRADE_SCHEMA,
        "grading": world_runner.GRADING_LABEL,
        "run": {
            "kind": receipt["kind"],
            "preregistered": bool(receipt["preregistered"]),
            "preregistration": receipt.get("preregistration"),
            "started_at_utc": manifest["started_at_utc"],
            "completed_at_utc": manifest["completed_at_utc"],
            "backend": receipt.get("backend"),
            "warning": receipt.get("warning"),
            "cli_reported_models": manifest.get("cli_reported_models", []),
            "environment": receipt.get("environment"),
        },
        "design": {k: header[k] for k in
                   ("arms", "runs", "seed", "limit", "n_leads", "n_trials",
                    "n_model_calls", "n_trials_per_arm")},
        "evidence": {
            "dataset_sha256": data_sha,
            "plan_sha256": manifest["plan_sha256"],
            "world_sha256": manifest["artifacts"][world_runner.WORLD_FILE],
            "decisions_sha256":
                manifest["artifacts"][world_runner.DECISIONS_FILE],
            "receipt_sha256":
                manifest["artifacts"][world_runner.RECEIPT_FILE],
            "manifest_seal_sha256": manifest["seal_sha256"],
            "event_chain_head": manifest["event_chain_head"],
        },
        "integrity_checks": checks,
        "arms": arms,
        "comparisons": comparisons,
        "criteria": criteria,
        "self_report_diagnostics": self_report_diagnostics(graded,
                                                           decisions),
    }


def _resolve_criteria(receipt: Dict[str, Any], manifest: Dict[str, Any],
                      plan: Dict[str, Any],
                      prereg_manifest_path: Optional[str],
                      criteria_demo_path: Optional[str]
                      ) -> Optional[Dict[str, Any]]:
    if receipt.get("preregistered"):
        if criteria_demo_path:
            raise IntegrityError(
                "a preregistered run takes its criteria from its own "
                "preregistration, not a demo manifest")
        binding = receipt.get("preregistration") or {}
        if not prereg_manifest_path:
            raise IntegrityError(
                "this run is preregistered: pass its preregistration "
                f"manifest ({binding.get('manifest_path')})")
        if integrity.sha256_file(prereg_manifest_path) != binding.get(
                "manifest_sha256"):
            raise IntegrityError(
                "preregistration manifest does not match the sha256 in "
                "the run receipt")
        prereg = _load_json(prereg_manifest_path, "preregistration manifest")
        slot = {"preregistered-primary": "primary",
                "preregistered-smoke": "smoke"}.get(receipt["kind"])
        if slot is None:
            raise IntegrityError(f"unknown run kind {receipt['kind']!r}")
        pinned = prereg["design"][slot]
        if (pinned["plan_sha256"] != manifest["plan_sha256"]
                or prereg["design"]["dataset"]["sha256"]
                != plan["header"]["dataset_sha256"]):
            raise IntegrityError(
                "run does not match the preregistered plan or dataset")
        if slot == "smoke":
            return {"source": prereg["id"], "applies": False,
                    "note": "preregistered SMOKE run: a pipeline health "
                            "check, outside the primary counts; no "
                            "criteria are evaluated on it",
                    "spec": None}
        return {"source": prereg["id"], "applies": True,
                "note": "criteria fixed in the preregistration before "
                        "the run; descriptive thresholds, not "
                        "significance tests",
                "spec": prereg["decision_criteria"]}
    if prereg_manifest_path:
        raise IntegrityError(
            "this run is not preregistered; a preregistration manifest "
            "cannot be attached to it after the fact")
    if criteria_demo_path:
        prereg = _load_json(criteria_demo_path, "preregistration manifest")
        return {"source": prereg["id"], "applies": True,
                "note": "FORMAT DEMONSTRATION ONLY: this run is not "
                        "preregistered; the criteria are applied to show "
                        "what the report will contain, and test nothing",
                "spec": prereg["decision_criteria"]}
    return None


def receipt_prereg_path(run_dir: str) -> Optional[str]:
    """Repository-relative manifest path named in a preregistered run's
    receipt, or None for a run that is not preregistered."""
    path = os.path.join(run_dir, world_runner.RECEIPT_FILE)
    if not os.path.isfile(path):
        return None
    receipt = _load_json(path, "receipt")
    if not receipt.get("preregistered"):
        return None
    return (receipt.get("preregistration") or {}).get("manifest_path")


def dump_grade(grade: Dict[str, Any]) -> str:
    return json.dumps(grade, indent=1, sort_keys=True) + "\n"
