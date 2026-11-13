"""The eval harness: arms, repetitions, and the results record.

Arms:
- treatment: the pipeline prompt on the real leads.
- placebo:   the same prompts, but each lead's observable attributes are
             swapped with another lead's (a seeded derangement) while the
             truth label stays put. If measured accuracy survives the placebo,
             the number is not coming from the leads.
- baseline:  a deterministic rules-only qualifier (no model), the "what you
             already have for free" reference point.

Every call is recorded as one JSONL row. Metrics are computed separately
(metrics.py) so the results file is the single source of truth.
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import asdict
from typing import Any, Dict, Iterable, Iterator, List, Optional

from . import pipeline
from .backends import BackendResponse

ARMS = ["treatment", "placebo", "baseline"]


def load_leads(path: str) -> List[Dict[str, Any]]:
    leads = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                leads.append(json.loads(line))
    return leads


def _derangement(n: int, seed: int) -> List[int]:
    """A permutation with no fixed points (so no lead keeps its own signals)."""
    rng = random.Random(seed)
    perm = list(range(n))
    while True:
        rng.shuffle(perm)
        if all(perm[i] != i for i in range(n)):
            return perm


def _placebo_lead(leads: List[Dict[str, Any]], target: int,
                  source: int) -> Dict[str, Any]:
    """Lead carrying `source`'s observable attributes but `target`'s truth."""
    src = leads[source]
    tgt = leads[target]
    return {
        "id": tgt["id"],
        "tricky": tgt["tricky"],
        "company": src["company"],
        "contact": src["contact"],
        "signals": src["signals"],
        "truth": tgt["truth"],
    }


def rules_baseline(lead: Dict[str, Any]) -> pipeline.QualificationCall:
    """Deterministic rules-only qualifier: the no-model reference point."""
    employees = lead["company"]["employees"]
    sig = lead["signals"]
    if sig["domain_claimed"] or (employees >= 1000 and sig["seats_active"] > 10):
        tier = "enterprise"
    elif sig["seats_active"] <= 2 and not sig["asked_about_pricing"]:
        tier = "personal_dev"
    else:
        tier = "team"
    route = {"enterprise": "sales", "team": "sales_assist",
             "personal_dev": "self_serve"}[tier]
    return pipeline.QualificationCall(tier=tier, route=route, confidence=1.0,
                                      reason="rules baseline")


def run_arm(leads: List[Dict[str, Any]], backend, arm: str, runs: int,
            seed: int, limit: Optional[int] = None,
            sleep_s: float = 0.0) -> Iterator[Dict[str, Any]]:
    selected = leads[:limit] if limit else leads
    perm = _derangement(len(selected), seed) if arm == "placebo" else None
    for run_index in range(runs):
        for pos, lead in enumerate(selected):
            shown = (_placebo_lead(selected, pos, perm[pos])
                     if arm == "placebo" else lead)
            if arm == "baseline":
                call = rules_baseline(shown)
                resp = BackendResponse(
                    raw_text=json.dumps(asdict(call)), call=call)
            else:
                # A CLI failure raises out of here and aborts the run on
                # the first failure; only parse problems become error rows.
                resp = backend.qualify(pipeline.build_prompt(shown),
                                       run_index=run_index)
            yield {
                "arm": arm,
                "run_index": run_index,
                "lead_id": lead["id"],
                "tricky": bool(lead["tricky"]),
                "true_tier": lead["truth"]["tier"],
                "true_route": lead["truth"]["route"],
                "pred_tier": resp.call.tier if resp.call else None,
                "pred_route": resp.call.route if resp.call else None,
                "confidence": resp.call.confidence if resp.call else None,
                "parse_ok": resp.call is not None,
                "error": resp.error,
            }
            if sleep_s:
                time.sleep(sleep_s)


def run_all(leads: List[Dict[str, Any]], backend, arms: Iterable[str],
            runs: int, seed: int, out_path: str,
            limit: Optional[int] = None) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    # Write to a sibling .partial file and move it into place only on
    # success. On abort the .partial file is PRESERVED (it is evidence of
    # how far the run got) and any previous complete results file at
    # out_path is left untouched.
    tmp_path = out_path + ".partial"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            for arm in arms:
                n = 0
                for row in run_arm(leads, backend, arm, runs, seed,
                                   limit=limit):
                    fh.write(json.dumps(row, sort_keys=True) + "\n")
                    n += 1
                counts[arm] = n
    except BaseException:
        # Do not delete tmp_path: the partial output stays on disk.
        raise
    import os
    os.replace(tmp_path, out_path)
    return counts
