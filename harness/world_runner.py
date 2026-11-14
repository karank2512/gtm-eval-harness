"""v2 runner: every decision is applied to the simulated CRM world.

What this adds over the v1 runner (runner.py, kept for reproducing v1):

- The runner only ever holds the MODEL-FACING view of the dataset: ids,
  company, contact, signals. Truth labels and the `tricky` flag are
  stripped before the first trial; correctness is decided later, offline,
  by world_grade.py from the dataset file itself.
- A sealed trial plan (every planned arm/run/lead identity, including the
  placebo signal mapping) is written before the first call.
- Each accepted decision is applied to the CRM world through the narrow
  WorldHandle API; unparseable answers are recorded as rejections and
  leave the lead unqualified and unrouted.
- Output is a run DIRECTORY built at `<run_dir>.partial` and renamed into
  place only on completion. An existing run directory is never
  overwritten, and an aborted run keeps its partial directory with an
  ABORTED.json and no manifest, so it can never be graded as complete.

Fail-fast is unchanged from v1: the first CLI failure aborts the run, with
no retries.
"""

from __future__ import annotations

import datetime
import itertools
import json
import os
import platform
import sqlite3
import stat
import sys
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import integrity, pipeline, runner
from .backends import BackendResponse
from .world import CRMWorld, trial_id_for

PLAN_SCHEMA = "gtm-trial-plan/1"
RECEIPT_SCHEMA = "gtm-run-receipt/1"
MANIFEST_SCHEMA = "gtm-world-run/1"
GRADING_LABEL = "v2-world-state"
MODEL_ARMS = ["treatment", "placebo"]

PLAN_FILE = "plan.json"
RECEIPT_FILE = "receipt.json"
WORLD_FILE = "world.sqlite"
DECISIONS_FILE = "decisions.jsonl"
MANIFEST_FILE = "manifest.json"
ABORTED_FILE = "ABORTED.json"
SEALED_FILES = [PLAN_FILE, RECEIPT_FILE, WORLD_FILE, DECISIONS_FILE]

MOCK_WARNING = ("MOCK BACKEND: deterministic test double, not a language "
                "model. These numbers check harness math only.")
STOPPING_RULE = ("abort on the first CLI failure, no retries; an aborted "
                 "run has no manifest and is never graded as complete")


class RunDirError(RuntimeError):
    """The run directory cannot be used (it exists, or a partial exists)."""


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------- dataset

def load_dataset(path: str) -> List[Dict[str, Any]]:
    """Load and validate the labeled dataset (ids unique, labels valid)."""
    rows = integrity.load_jsonl(path)
    if not rows:
        raise integrity.IntegrityError(f"{path}: dataset is empty")
    for row in rows:
        for key in ("id", "tricky", "company", "contact", "signals",
                    "truth"):
            if key not in row:
                raise integrity.IntegrityError(
                    f"{path}: lead {row.get('id')!r} is missing {key!r}")
        truth = row["truth"]
        if (truth.get("tier") not in pipeline.TIERS
                or truth.get("route") not in pipeline.ROUTES):
            raise integrity.IntegrityError(
                f"{path}: lead {row['id']!r} has an invalid truth label")
    dupes = integrity.find_duplicates(r["id"] for r in rows)
    if dupes:
        raise integrity.IntegrityError(
            f"{path}: duplicate lead ids {dupes[:5]}")
    return rows


def model_facing(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The only view of the dataset the runner works with: no truth
    labels, no `tricky` flag."""
    return [{"id": r["id"], "company": r["company"],
             "contact": r["contact"], "signals": r["signals"]}
            for r in rows]


# ------------------------------------------------------------------ plan

def build_plan(lead_ids: Sequence[str], dataset_sha256: str,
               arms: Sequence[str], runs: int, seed: int,
               limit: Optional[int] = None) -> Dict[str, Any]:
    """The expected trial inventory: one identity per arm x run x lead.

    Deterministic in (lead id order, dataset hash, arms, runs, seed,
    limit) - no timestamps - so the same design always hashes the same.
    The placebo arm's signal mapping (which lead's signals each lead is
    shown with) is part of the plan.
    """
    for arm in arms:
        if arm not in runner.ARMS:
            raise ValueError(f"unknown arm: {arm}")
    if integrity.find_duplicates(arms):
        raise ValueError("duplicate arms")
    if runs < 1:
        raise ValueError("runs must be >= 1")
    if limit is not None and limit < 1:
        raise ValueError("limit must be >= 1")
    selected = list(lead_ids[:limit] if limit else lead_ids)
    if len(selected) < 2 and "placebo" in arms:
        raise ValueError("the placebo arm needs at least 2 leads")
    perm = (runner._derangement(len(selected), seed)
            if "placebo" in arms else None)
    trials = []
    for arm in arms:
        for run_index in range(runs):
            for position, lead_id in enumerate(selected):
                shown = (selected[perm[position]] if arm == "placebo"
                         else lead_id)
                trials.append({
                    "trial_id": trial_id_for(arm, run_index, lead_id),
                    "arm": arm, "run_index": run_index,
                    "lead_id": lead_id, "position": position,
                    "shown_lead_id": shown})
    header = {
        "schema": PLAN_SCHEMA,
        "dataset_sha256": dataset_sha256,
        "arms": list(arms), "runs": runs, "seed": seed,
        "limit": limit, "n_leads": len(selected),
        "lead_ids": selected,
        "n_trials": len(trials),
        "n_model_calls": sum(1 for t in trials if t["arm"] in MODEL_ARMS),
        "n_trials_per_arm": len(selected) * runs,
    }
    return {"header": header, "trials": trials}


def dump_plan(plan: Dict[str, Any]) -> str:
    """Canonical file text for a plan: one trial per line, sorted keys."""
    lines = ['{"header": ' + integrity.canonical_json(plan["header"]) + ",",
             '"trials": [']
    body = [integrity.canonical_json(t) for t in plan["trials"]]
    lines.append(",\n".join(body))
    lines.append("]}")
    return "\n".join(lines) + "\n"


def plan_sha256(plan: Dict[str, Any]) -> str:
    return integrity.sha256_text(dump_plan(plan))


def load_plan(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    try:
        plan = json.loads(text)
        canonical = dump_plan(plan)
    except (ValueError, KeyError, TypeError) as exc:
        raise integrity.IntegrityError(
            f"{path}: not a readable trial plan ({exc})") from exc
    if canonical != text:
        raise integrity.IntegrityError(
            f"{path}: plan is not in canonical form")
    return plan


# --------------------------------------------------------------- receipt

def public_backend_detail(backend) -> Dict[str, Any]:
    """Backend description without machine-local paths."""
    detail = dict(backend.describe())
    command = detail.pop("command", None)
    if command is not None:
        detail["launcher"] = ("claude on PATH" if command == "claude"
                              else "custom launcher (path not recorded)")
    return detail


def make_receipt(kind: str, plan: Dict[str, Any], backend,
                 preregistration: Optional[Dict[str, Any]] = None,
                 started_at_utc: Optional[str] = None) -> Dict[str, Any]:
    """The run receipt, written before the first model call."""
    header = plan["header"]
    is_mock = getattr(backend, "name", "") == "mock-test-only"
    return {
        "schema": RECEIPT_SCHEMA,
        "kind": kind,
        "grading": GRADING_LABEL,
        "preregistered": preregistration is not None,
        "preregistration": preregistration,
        "started_at_utc": started_at_utc or utc_now(),
        "dataset_sha256": header["dataset_sha256"],
        "plan_sha256": plan_sha256(plan),
        "config": {"arms": header["arms"], "runs": header["runs"],
                   "seed": header["seed"], "limit": header["limit"],
                   "n_leads": header["n_leads"],
                   "n_trials": header["n_trials"],
                   "n_model_calls": header["n_model_calls"]},
        "backend": public_backend_detail(backend),
        "warning": MOCK_WARNING if is_mock else None,
        "stopping_rule": STOPPING_RULE,
        "environment": {"python": platform.python_version(),
                        "sqlite": sqlite3.sqlite_version,
                        "platform": sys.platform},
    }


def _write_json(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")


def seal_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    body = {k: v for k, v in manifest.items() if k != "seal_sha256"}
    sealed = dict(body)
    sealed["seal_sha256"] = integrity.sha256_canonical(body)
    return sealed


# ------------------------------------------------------------------- run

def _decide(trial: Dict[str, Any], shown: Dict[str, Any],
            backend) -> BackendResponse:
    if trial["arm"] == "baseline":
        call = runner.rules_baseline(shown)
        return BackendResponse(
            raw_text=json.dumps({"tier": call.tier, "route": call.route,
                                 "confidence": call.confidence,
                                 "reason": call.reason}), call=call)
    # A CLI failure raises BackendError out of here and aborts the run on
    # the first failure; only an unparseable answer comes back as a row.
    return backend.qualify(pipeline.build_prompt(shown),
                           run_index=trial["run_index"])


def run_world(leads: Sequence[Dict[str, Any]], plan: Dict[str, Any],
              backend, run_dir: str, receipt: Dict[str, Any],
              port_wrapper: Optional[Callable[[Any], Any]] = None,
              clock: Callable[[], str] = utc_now) -> Dict[str, Any]:
    """Execute a plan against a fresh CRM world. Returns the manifest.

    `leads` is the model-facing view (see model_facing); anything else on
    a lead record is ignored. `port_wrapper`, if given, wraps each
    WorldHandle - tests use it to inject CRM faults (dropped dispatch,
    wrong queue) and check that the grader catches them. The CLI never
    sets it.
    """
    run_dir = os.path.normpath(run_dir)
    partial = run_dir + ".partial"
    if os.path.exists(run_dir):
        raise RunDirError(
            f"{run_dir} already exists; a completed run is never "
            "overwritten")
    if os.path.exists(partial):
        raise RunDirError(
            f"{partial} exists from an earlier incomplete run; it is kept "
            "as evidence - choose a new run directory")
    header = plan["header"]
    by_id = {lead["id"]: lead for lead in model_facing(leads)}
    missing = [i for i in header["lead_ids"] if i not in by_id]
    if missing:
        raise integrity.IntegrityError(
            f"plan names leads that are not in the dataset: {missing[:5]}")
    if receipt.get("plan_sha256") != plan_sha256(plan):
        raise integrity.IntegrityError("receipt does not match the plan")

    os.makedirs(partial)
    plan_path = os.path.join(partial, PLAN_FILE)
    with open(plan_path, "w", encoding="utf-8") as fh:
        fh.write(dump_plan(plan))
    receipt_path = os.path.join(partial, RECEIPT_FILE)
    _write_json(receipt_path, receipt)
    receipt_sha = integrity.sha256_file(receipt_path)

    crm = None
    log = None
    logged = 0
    model_calls = 0
    reported_models = set()
    try:
        crm = CRMWorld.create(os.path.join(partial, WORLD_FILE),
                              plan_sha256=receipt["plan_sha256"],
                              dataset_sha256=header["dataset_sha256"],
                              receipt_sha256=receipt_sha)
        log = open(os.path.join(partial, DECISIONS_FILE), "w",
                   encoding="utf-8")
        groups = itertools.groupby(
            plan["trials"], key=lambda t: (t["arm"], t["run_index"]))
        for (arm, run_index), trials in groups:
            handle = crm.open_world(arm, run_index, header["lead_ids"])
            port = port_wrapper(handle) if port_wrapper else handle
            for trial in trials:
                shown = by_id[trial["shown_lead_id"]]
                if arm != "baseline":
                    model_calls += 1
                resp = _decide(trial, shown, backend)
                if resp.call is not None:
                    crm_receipt = port.apply_qualification(
                        trial["trial_id"], trial["lead_id"],
                        resp.call.tier, resp.call.route)
                else:
                    crm_receipt = port.record_rejection(
                        trial["trial_id"], trial["lead_id"],
                        "parse_failure")
                meta = resp.meta or {}
                reported_models.update(meta.get("reported_models", []))
                # Self-report log. It carries no truth labels and is never
                # used to decide correctness; the grader takes only the
                # self-reported confidence from it.
                row = {
                    "trial_id": trial["trial_id"], "arm": arm,
                    "run_index": run_index, "lead_id": trial["lead_id"],
                    "shown_lead_id": trial["shown_lead_id"],
                    "source": ("rules-baseline" if arm == "baseline"
                               else "model"),
                    "parse_ok": resp.call is not None,
                    "claimed_tier": resp.call.tier if resp.call else None,
                    "claimed_route": resp.call.route if resp.call else None,
                    "confidence": (resp.call.confidence if resp.call
                                   else None),
                    "error": resp.error,
                    "raw_sha256": integrity.sha256_text(resp.raw_text or ""),
                    "crm_receipt": crm_receipt,
                }
                log.write(json.dumps(row, sort_keys=True) + "\n")
                log.flush()
                logged += 1
            handle.close()
        seal = crm.seal()
        log.close()
    except BaseException as exc:
        # Keep everything written so far, mark it aborted, never complete.
        if log is not None and not log.closed:
            log.close()
        if crm is not None:
            crm.close()
        _write_json(os.path.join(partial, ABORTED_FILE), {
            "state": "aborted",
            "aborted_at_utc": clock(),
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "decisions_logged": logged,
            "planned_trials": header["n_trials"],
            "note": ("incomplete run: no manifest, not gradeable, not "
                     "part of any reported count"),
        })
        raise

    manifest = seal_manifest({
        "schema": MANIFEST_SCHEMA,
        "state": "complete",
        "grading": GRADING_LABEL,
        "kind": receipt["kind"],
        "preregistered": receipt["preregistered"],
        "started_at_utc": receipt["started_at_utc"],
        "completed_at_utc": clock(),
        "dataset_sha256": header["dataset_sha256"],
        "plan_sha256": receipt["plan_sha256"],
        "artifacts": {name: integrity.sha256_file(
            os.path.join(partial, name)) for name in SEALED_FILES},
        "counts": {"planned_trials": header["n_trials"],
                   "decisions_logged": logged,
                   "model_calls": model_calls,
                   "worlds": len(header["arms"]) * header["runs"],
                   "events": seal["event_count"]},
        "event_chain_head": seal["event_chain_head"],
        "cli_reported_models": sorted(reported_models),
        "warning": receipt.get("warning"),
    })
    _write_json(os.path.join(partial, MANIFEST_FILE), manifest)
    # Advisory only: read-only bits stop accidental edits, not the owner.
    for name in SEALED_FILES + [MANIFEST_FILE]:
        os.chmod(os.path.join(partial, name),
                 stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    os.rename(partial, run_dir)
    return manifest
