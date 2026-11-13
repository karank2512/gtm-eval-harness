"""REPORT.md generation. Every figure is recomputed from results JSONL."""

from __future__ import annotations

import datetime
from typing import Any, Dict, Optional

from . import metrics


def _pct(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _acc_line(label: str, d: Dict[str, Any]) -> str:
    return f"| {label} | {d['correct']}/{d['n']} | {_pct(d['accuracy'])} |"


def _mean_confidence(cal: Dict[str, Any]) -> Optional[float]:
    n = sum(b["n"] for b in cal.get("bins", []))
    if not n:
        return None
    return sum(b["n"] * b["mean_confidence"] for b in cal["bins"]) / n


def _calibration_phrase(acc: Optional[float], mean_conf: Optional[float],
                        ece: float) -> str:
    """Describe calibration direction honestly instead of calling ECE 'good'."""
    if acc is None or mean_conf is None:
        return f"ECE {ece:.3f} (no direction estimate)"
    gap = acc - mean_conf
    if gap > 0.03:
        return (f"underconfident on this set: mean confidence "
                f"{mean_conf:.2f} vs actual tier accuracy {_pct(acc)} "
                f"(ECE {ece:.3f})")
    if gap < -0.03:
        return (f"overconfident on this set: mean confidence "
                f"{mean_conf:.2f} vs actual tier accuracy {_pct(acc)} "
                f"(ECE {ece:.3f})")
    return (f"well matched on this set: mean confidence {mean_conf:.2f} "
            f"vs actual tier accuracy {_pct(acc)} (ECE {ece:.3f})")


def render(summary: Dict[str, Any], meta: Dict[str, Any]) -> str:
    lines = []
    lines.append("# GTM lead-qualification eval - report")
    lines.append("")
    lines.append(f"Generated {datetime.date.today().isoformat()} from "
                 f"`{meta.get('results_path', 'results file')}`. "
                 "Every number below is recomputed from that file by "
                 "`scripts/report.py`; none are typed by hand.")
    lines.append("")
    lines.append("## Setup")
    lines.append("")
    lines.append(f"- backend: `{meta.get('backend', 'unknown')}`"
                 + (f" (model: `{meta['model']}`)" if meta.get("model") else ""))
    if meta.get("backend") == "claude-code":
        lines.append("- runtime: local Claude Code CLI on a Claude "
                     "subscription - no API key, no usage billing; "
                     "qualification calls run with tool use disabled")
    lines.append(f"- leads: {meta.get('n_leads', 'n/a')} "
                 f"(synthetic, seed {meta.get('seed', 'n/a')})")
    lines.append(f"- runs per arm: {meta.get('runs', 'n/a')}")
    lines.append(f"- arms: {', '.join(summary.keys())}")
    if meta.get("warning"):
        lines.append(f"- **{meta['warning']}**")
    lines.append("")

    treat = summary.get("treatment")
    base = summary.get("baseline")
    if treat:
        ta = treat["tier_accuracy"]
        ra = treat["route_accuracy"]
        tg = treat["tricky_gap"]
        cal = treat["calibration"]
        flip = treat["flip_rate"]
        mean_conf = _mean_confidence(cal)
        lines.append("## Headline")
        lines.append("")
        lines.append(
            f"1. Tier calls are near ceiling on this dataset: "
            f"{_pct(ta['accuracy'])} of lead-runs tiered correctly "
            f"({ta['correct']}/{ta['n']}).")
        route_bit = (
            f"Routing is not: {_pct(ra['accuracy'])} of lead-runs routed "
            f"correctly ({ra['correct']}/{ra['n']})")
        if base:
            bra = base["route_accuracy"]
            delta = ra["correct"] - bra["correct"]
            route_bit += (
                f" - {delta:+d} lead-runs vs the deterministic rules "
                f"baseline ({bra['correct']}/{bra['n']}, "
                f"{_pct(bra['accuracy'])}), so on this dataset the model's "
                f"routing buys almost nothing over free rules")
        lines.append(f"2. {route_bit}.")
        tricky = tg["tricky"]
        clean = tg["clean"]
        if (tricky["accuracy"] is not None and clean["accuracy"] is not None
                and tricky["accuracy"] >= clean["accuracy"]):
            lines.append(
                f"3. The leads designed to fool the qualifier did not: "
                f"{tricky['correct']}/{tricky['n']} tricky lead-runs tiered "
                f"correctly vs {clean['correct']}/{clean['n']} clean. The "
                f"traps were calibrated for weaker qualifiers - a negative "
                f"result, reported as one.")
        else:
            lines.append(
                f"3. On leads designed to fool it, tier accuracy drops to "
                f"{_pct(tricky['accuracy'])} ({tricky['correct']}/"
                f"{tricky['n']}) vs {_pct(clean['accuracy'])} on clean "
                f"leads ({clean['correct']}/{clean['n']}).")
        if cal.get("ece") is not None:
            lines.append(
                f"4. Confidence is "
                f"{_calibration_phrase(ta['accuracy'], mean_conf, cal['ece'])}, "
                f"Brier {cal['brier']:.3f} over {cal['n']} scored calls.")
        if flip.get("mean_per_lead_flip") is not None:
            lines.append(
                f"5. Re-running the same leads flips the tier call on "
                f"{_pct(flip['mean_per_lead_flip'])} of lead-runs "
                f"({flip['leads_with_multiple_runs']} leads x repeated runs).")
        lines.append("")

    for arm, s in summary.items():
        lines.append(f"## Arm: {arm}")
        lines.append("")
        pf = s["parse_failures"]
        lines.append(f"- scored rows: {pf['n'] - pf['failures']}/{pf['n']}"
                     f" (unparseable: {pf['failures']})")
        lines.append("")
        lines.append("### Tier accuracy by true segment")
        lines.append("")
        lines.append("| true segment | correct/n | accuracy |")
        lines.append("|---|---|---|")
        for seg, d in s["tier_accuracy"]["by_segment"].items():
            lines.append(_acc_line(seg, d))
        lines.append(_acc_line("**all**", s["tier_accuracy"]))
        lines.append("")
        lines.append("### Route accuracy by true segment")
        lines.append("")
        lines.append("| true segment | correct/n | accuracy |")
        lines.append("|---|---|---|")
        for seg, d in s["route_accuracy"]["by_segment"].items():
            lines.append(_acc_line(seg, d))
        lines.append(_acc_line("**all**", s["route_accuracy"]))
        lines.append("")
        lines.append("### Confusions (tier), most frequent first")
        lines.append("")
        lines.append("| true | predicted | n |")
        lines.append("|---|---|---|")
        for c in s["tier_confusion"]:
            lines.append(f"| {c['true']} | {c['pred']} | {c['n']} |")
        lines.append("")
        cal = s["calibration"]
        if cal.get("ece") is not None:
            lines.append(f"### Calibration (ECE {cal['ece']:.3f}, "
                         f"Brier {cal['brier']:.3f}, n={cal['n']})")
            lines.append("")
            lines.append("| confidence bin | n | mean conf | accuracy |")
            lines.append("|---|---|---|---|")
            for b in cal["bins"]:
                lines.append(f"| {b['bin']} | {b['n']} | "
                             f"{b['mean_confidence']:.2f} | "
                             f"{_pct(b['accuracy'])} |")
            lines.append("")
        flip = s["flip_rate"]
        if flip.get("run_accuracy"):
            lines.append("### Run-to-run stability")
            lines.append("")
            lines.append("| run | correct/n | accuracy |")
            lines.append("|---|---|---|")
            for run_idx, d in flip["run_accuracy"].items():
                lines.append(f"| {run_idx} | {d['correct']}/{d['n']} | "
                             f"{_pct(d['accuracy'])} |")
            lines.append("")
            if flip.get("mean_per_lead_flip") is not None:
                lines.append(
                    f"Mean per-lead flip rate: "
                    f"{_pct(flip['mean_per_lead_flip'])} across "
                    f"{flip['leads_with_multiple_runs']} leads; accuracy "
                    f"spread across runs: {_pct(flip['accuracy_spread'])}.")
                lines.append("")

    lines.append("## Limits")
    lines.append("")
    n_leads = meta.get("n_leads", "n/a")
    runs = meta.get("runs", "n/a")
    lines.append(
        f"- {n_leads} synthetic leads x {runs} repeats each: the per-arm "
        "row counts are lead-runs, not independent leads. Repeated runs of "
        "one lead share its label and its signals.")
    lines.append(
        "- The placebo arm uses one fixed seeded derangement. A different "
        "permutation gives a different placebo number; treat it as a "
        "sanity floor, not a precise estimate.")
    lines.append(
        "- Labels are hand-designed and unambiguous by construction. Real "
        "funnel data has contested labels, missing signals and drift; "
        "accuracy here is an upper bound, not a promise.")
    lines.append(
        "- The dataset is synthetic and shaped like a generic PLG "
        "free-to-paid motion. It is not any company's production data.")
    lines.append(
        "- Every claim is about this prompt + this model + this dataset. "
        "Change any of the three and re-run before reusing a number.")
    lines.append("")
    lines.append("## How to reproduce")
    lines.append("")
    backend_cli = meta.get("backend_name_for_cli", "claude-code")
    model_flag = (f" --model {meta['model']}" if meta.get("model")
                  and backend_cli == "claude-code" else "")
    lines.append("```sh")
    lines.append(f"python3 run_eval.py --backend {backend_cli}{model_flag} "
                 f"--runs {meta.get('runs', 3)} --out results/results.jsonl")
    lines.append("python3 scripts/report.py --results results/results.jsonl "
                 "--out REPORT.md")
    lines.append("```")
    lines.append("")
    if backend_cli == "claude-code":
        lines.append("Runs execute through the local Claude Code CLI on a "
                     "Claude subscription; no API key is used and no usage "
                     "billing is involved. Pin the model explicitly as shown "
                     "so a report always names the model its numbers came "
                     "from.")
        lines.append("")
    return "\n".join(lines)
