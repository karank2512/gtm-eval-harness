"""REPORT.md generation. Every figure is recomputed from results JSONL."""

from __future__ import annotations

import datetime
from typing import Any, Dict, Optional

from . import metrics


def _pct(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _acc_line(label: str, d: Dict[str, Any]) -> str:
    return f"| {label} | {d['correct']}/{d['n']} | {_pct(d['accuracy'])} |"


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
    lines.append(f"- leads: {meta.get('n_leads', 'n/a')} "
                 f"(synthetic, seed {meta.get('seed', 'n/a')})")
    lines.append(f"- runs per arm: {meta.get('runs', 'n/a')}")
    lines.append(f"- arms: {', '.join(summary.keys())}")
    if meta.get("warning"):
        lines.append(f"- **{meta['warning']}**")
    lines.append("")

    treat = summary.get("treatment")
    if treat:
        ta = treat["tier_accuracy"]
        lines.append("## Headline")
        lines.append("")
        tg = treat["tricky_gap"]
        cal = treat["calibration"]
        flip = treat["flip_rate"]
        lines.append(
            f"1. The pipeline routes {_pct(ta['accuracy'])} of leads to the "
            f"right tier ({ta['correct']}/{ta['n']}).")
        lines.append(
            f"2. On leads designed to fool it, accuracy is "
            f"{_pct(tg['tricky']['accuracy'])} ({tg['tricky']['correct']}/"
            f"{tg['tricky']['n']}) vs {_pct(tg['clean']['accuracy'])} on "
            f"clean leads ({tg['clean']['correct']}/{tg['clean']['n']}).")
        lines.append(
            f"3. Confidence is calibrated to ECE "
            f"{cal['ece']:.3f} over {cal['n']} scored calls"
            if cal.get("ece") is not None else
            "3. No scored calls for calibration.")
        if flip.get("mean_per_lead_flip") is not None:
            lines.append(
                f"4. Re-running the same leads flips the tier call on "
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

    lines.append("## How to reproduce")
    lines.append("")
    lines.append("```sh")
    lines.append("python3 run_eval.py --backend "
                 f"{meta.get('backend_name_for_cli', 'claude-code')} "
                 f"--runs {meta.get('runs', 3)} --out results/results.jsonl")
    lines.append("python3 scripts/report.py --results results/results.jsonl "
                 "--out REPORT.md")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)
