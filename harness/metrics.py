"""Metrics over harness results. Every number carries its denominator."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List


def load_results(path: str) -> List[Dict[str, Any]]:
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _ok(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows if r["parse_ok"]]


def accuracy(rows: List[Dict[str, Any]], field: str = "tier") -> Dict[str, Any]:
    """Overall accuracy plus per-true-segment breakdown with denominators.

    field: "tier" or "route".
    """
    rows = _ok(rows)
    pred_key = f"pred_{field}"
    true_key = f"true_{field}"
    total = len(rows)
    correct = sum(1 for r in rows if r[pred_key] == r[true_key])
    by_segment: Dict[str, Dict[str, Any]] = {}
    seg_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        seg_rows[r[true_key]].append(r)
    for seg, group in sorted(seg_rows.items()):
        seg_correct = sum(1 for r in group if r[pred_key] == r[true_key])
        by_segment[seg] = {"n": len(group), "correct": seg_correct,
                           "accuracy": seg_correct / len(group) if group else None}
    return {"n": total, "correct": correct,
            "accuracy": correct / total if total else None,
            "by_segment": by_segment}


def tricky_gap(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Accuracy split by clean vs tricky leads (tier field)."""
    rows = _ok(rows)
    out = {}
    for label, flag in (("clean", False), ("tricky", True)):
        group = [r for r in rows if r["tricky"] is flag]
        correct = sum(1 for r in group if r["pred_tier"] == r["true_tier"])
        out[label] = {"n": len(group), "correct": correct,
                      "accuracy": correct / len(group) if group else None}
    return out


def confusion(rows: List[Dict[str, Any]], field: str = "tier"
              ) -> List[Dict[str, Any]]:
    """Confusion pairs sorted by count, most frequent first."""
    rows = _ok(rows)
    counts: Counter = Counter()
    for r in rows:
        counts[(r[f"true_{field}"], r[f"pred_{field}"])] += 1
    return [{"true": t, "pred": p, "n": n}
            for (t, p), n in counts.most_common()]


def calibration(rows: List[Dict[str, Any]], bins: int = 5) -> Dict[str, Any]:
    """ECE and Brier score of confidence vs tier correctness."""
    rows = [r for r in _ok(rows) if r["confidence"] is not None]
    n = len(rows)
    if not n:
        return {"n": 0, "ece": None, "brier": None, "bins": []}
    brier = sum((r["confidence"]
                 - (1.0 if r["pred_tier"] == r["true_tier"] else 0.0)) ** 2
                for r in rows) / n
    bucket_rows: List[List[Dict[str, Any]]] = [[] for _ in range(bins)]
    for r in rows:
        idx = min(bins - 1, int(r["confidence"] * bins))
        bucket_rows[idx].append(r)
    ece = 0.0
    bin_report = []
    for i, group in enumerate(bucket_rows):
        if not group:
            continue
        mean_conf = sum(r["confidence"] for r in group) / len(group)
        acc = sum(1 for r in group
                  if r["pred_tier"] == r["true_tier"]) / len(group)
        ece += len(group) / n * abs(mean_conf - acc)
        bin_report.append({"bin": f"{i / bins:.1f}-{(i + 1) / bins:.1f}",
                           "n": len(group), "mean_confidence": mean_conf,
                           "accuracy": acc})
    return {"n": n, "ece": ece, "brier": brier, "bins": bin_report}


def flip_rate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Run-to-run instability.

    per-lead flip: 1 - (largest share of any one tier across that lead's runs)
    winner_disagreement: share of lead pairs of runs whose per-run overall
    accuracies differ - reported as run accuracy spread instead, simpler:
    accuracy range across runs with denominators.
    """
    rows = _ok(rows)
    by_lead: Dict[str, List[str]] = defaultdict(list)
    for r in rows:
        by_lead[r["lead_id"]].append(r["pred_tier"])
    multi = {k: v for k, v in by_lead.items() if len(v) > 1}
    flips = []
    for lead_id, preds in sorted(multi.items()):
        share = Counter(preds).most_common(1)[0][1] / len(preds)
        flips.append({"lead_id": lead_id, "runs": len(preds),
                      "flip": 1.0 - share})
    mean_flip = (sum(f["flip"] for f in flips) / len(flips)) if flips else None
    by_run: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_run[r["run_index"]].append(r)
    run_acc = {}
    for run_index, group in sorted(by_run.items()):
        correct = sum(1 for r in group if r["pred_tier"] == r["true_tier"])
        run_acc[str(run_index)] = {"n": len(group), "correct": correct,
                                   "accuracy": correct / len(group)}
    accs = [v["accuracy"] for v in run_acc.values()]
    return {"leads_with_multiple_runs": len(multi),
            "mean_per_lead_flip": mean_flip,
            "run_accuracy": run_acc,
            "accuracy_spread": (max(accs) - min(accs)) if accs else None}


def parse_failures(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    bad = [r for r in rows if not r["parse_ok"]]
    return {"n": n, "failures": len(bad),
            "rate": len(bad) / n if n else None,
            "examples": [r["error"] for r in bad[:3]]}


def summarize_arm(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "rows": len(rows),
        "parse_failures": parse_failures(rows),
        "tier_accuracy": accuracy(rows, "tier"),
        "route_accuracy": accuracy(rows, "route"),
        "tricky_gap": tricky_gap(rows),
        "tier_confusion": confusion(rows, "tier"),
        "calibration": calibration(rows),
        "flip_rate": flip_rate(rows),
    }


def summarize(results_path: str) -> Dict[str, Any]:
    rows = load_results(results_path)
    by_arm: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_arm[r["arm"]].append(r)
    return {arm: summarize_arm(arm_rows)
            for arm, arm_rows in sorted(by_arm.items())}
