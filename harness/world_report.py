"""v2 report: rendered from an offline world-state grade, nothing else.

The renderer takes the grade produced by world_grade.grade_run and adds no
numbers of its own. The report date is the run's recorded completion time
(artifact metadata), never the wall clock, so regenerating the report on
another day produces the same bytes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _pct(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _cn(d: Dict[str, Any]) -> str:
    return f"{d['correct']}/{d['n']} ({_pct(d['accuracy'])})"


def _points(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{100 * x:+.1f}"


def _calibration_phrase(cal: Dict[str, Any]) -> str:
    gap = cal["accuracy"] - cal["mean_confidence"]
    if gap > 0.03:
        direction = "underconfident"
    elif gap < -0.03:
        direction = "overconfident"
    else:
        direction = "well matched"
    return (f"{direction} on this set: mean self-reported confidence "
            f"{cal['mean_confidence']:.2f} vs tier effect accuracy "
            f"{_pct(cal['accuracy'])} over the {cal['n']} lead-runs that "
            f"reported a confidence (ECE {cal['ece']:.3f}, Brier "
            f"{cal['brier']:.3f})")


def _condition_text(cond: Dict[str, Any]) -> str:
    c = cond["condition"]
    subject = c["metric"].replace("_", " ")
    if c.get("arm"):
        subject += f", {c['arm']}"
    if c.get("vs"):
        subject += f" vs {c['vs']}"
    state = {True: "met", False: "NOT met", None: "not evaluable"}[
        cond["met"]]
    observed = cond["observed"]
    if "diff" in c["metric"] and cond["value"] is not None:
        observed += f" ({100 * cond['value']:+.1f} points)"
    return f"{subject} {c['op']} {c['value']}: observed {observed} - {state}"


def render(grade: Dict[str, Any]) -> str:
    run = grade["run"]
    design = grade["design"]
    evidence = grade["evidence"]
    arms = grade["arms"]
    backend = run.get("backend") or {}
    is_mock = bool(run.get("warning"))
    is_smoke = run["kind"] == "preregistered-smoke"
    L: List[str] = []
    add = L.append

    title = "# GTM lead-qualification eval - v2 world-state report"
    if is_mock:
        title += " (MOCK - not a model result)"
    elif is_smoke:
        title += " (SMOKE - outside the primary counts)"
    add(title)
    add("")
    add(f"Generated from a sealed v2 run completed "
        f"{run['completed_at_utc']} (world database sha256 "
        f"`{evidence['world_sha256'][:16]}`). Every number below is "
        "recomputed offline by `scripts/world_report.py` from the CRM "
        "world database, the dataset's own labels and the sealed trial "
        "plan; none are typed by hand. The date is the run's recorded "
        "completion time, not the day this file was rendered.")
    add("")
    if is_mock:
        add(f"**{run['warning']}**")
        add("")
    if is_smoke:
        add("**SMOKE RUN: a pipeline health check on the first "
            f"{design['n_leads']} leads. Its numbers are outside the "
            "primary counts and are never pooled with them.**")
        add("")
    if not run["preregistered"] and not is_mock:
        add("**NOT PREREGISTERED: an exploratory run. Nothing here is a "
            "test of a prespecified hypothesis.**")
        add("")

    add("## What is graded here")
    add("")
    add("- **Effects, not answers.** A lead-run is correct only if the "
        "simulated CRM shows it: the lead record carries the true tier, "
        "the lead is a member of the true route's queue, and a dispatch "
        "event with a valid receipt agrees with that state. The model's "
        "JSON, its `reason` text and the runner's log are not evidence "
        "of correctness.")
    add("- **Failures stay in the denominator.** Unparseable answers, "
        "dropped dispatches and inconsistent effects count as wrong; "
        "every accuracy below is over all planned lead-runs.")
    add("- **Confidence is a self-report.** Calibration compares the "
        "confidence the qualifier stated (taken from the decisions log) "
        "with what the world shows. It is the one figure here that rests "
        "on the log, and it is secondary.")
    add("- **Boundary.** The CRM is a local simulator owned by this "
        "harness, not a production CRM and not an independent security "
        "boundary. The separation that matters is from the model under "
        "test, which runs tool-free and never sees the labels, the plan "
        "or the database. The hashes below are consistency links; they "
        "are not tamperproof against whoever owns the files.")
    add("")

    add("## Setup")
    add("")
    line = f"- backend: `{backend.get('backend', 'unknown')}`"
    if backend.get("model"):
        line += f" (model requested: `{backend['model']}`)"
    add(line)
    if backend.get("backend") == "claude-code":
        add("- runtime: local Claude Code CLI on a Claude subscription - "
            "no API key, no usage billing; tool use disabled "
            "(`--tools ''`), no session persistence, each call started "
            "from an empty scratch directory outside the repository, so "
            "each call is a stateless prompt-to-JSON completion")
        reported = run.get("cli_reported_models") or []
        add("- model identifiers reported back by the CLI (recorded, not "
            "enforced): "
            + (", ".join(f"`{m}`" for m in reported) if reported
               else "none reported"))
        add("- fail-fast: the run aborts on the first CLI failure, no "
            "retries; an aborted run has no manifest and cannot be "
            "graded")
    add(f"- leads: {design['n_leads']} independent cases (synthetic, "
        f"seed {design['seed']})"
        + (f", first {design['limit']} of the dataset"
           if design.get("limit") else ""))
    add(f"- runs per arm: {design['runs']} -> "
        f"{design['n_trials_per_arm']} lead-runs per arm")
    add(f"- arms: {', '.join(design['arms'])}")
    add(f"- decisions: {design['n_trials']} planned, of which "
        f"{design['n_model_calls']} are model calls (the baseline arm is "
        "deterministic rules)")
    add(f"- dataset sha256: `{evidence['dataset_sha256']}`")
    add(f"- trial plan sha256: `{evidence['plan_sha256']}`")
    add("")

    add("## Preregistration")
    add("")
    binding = run.get("preregistration")
    if run["preregistered"] and binding:
        add(f"- id: `{binding['id']}` ({binding['document_path']})")
        add(f"- verified before the first model call at git commit "
            f"`{binding['git_commit']}` (commit time "
            f"{binding['git_commit_time']}); run started "
            f"{run['started_at_utc']}")
        add(f"- manifest sha256 `{binding['manifest_sha256']}`, document "
            f"sha256 `{binding['document_sha256']}`")
        add(f"- attempt {binding['attempt']}; earlier attempts on disk "
            "when this one started: "
            + (", ".join(f"{a['directory']} ({a['state']})"
                         for a in binding["earlier_attempts"])
               if binding["earlier_attempts"] else "none"))
        add("- This is not held-out confirmatory evidence: the v1 run on "
            "the same public synthetic dataset was seen before the "
            "preregistration was written. v2 is an engineering "
            "replication under stricter grading.")
    else:
        add("This run is not preregistered.")
    add("")

    add("## Integrity checks")
    add("")
    add("All of the following passed; the grader refuses to produce a "
        "score otherwise.")
    add("")
    for check in grade["integrity_checks"]:
        add(f"- {check['check']}: {check['detail']}")
    add("")

    add("## Primary outcomes: effect accuracy")
    add("")
    add("| arm | tier effect | route effect | both | delivered | "
        "rejected (unparseable) | no effect | inconsistent |")
    add("|---|---|---|---|---|---|---|---|")
    for arm, s in arms.items():
        st = s["effect_status"]
        add(f"| {arm} | {_cn(s['tier_effect'])} | {_cn(s['route_effect'])} "
            f"| {_cn(s['both_effects'])} | {st['applied']} | "
            f"{st['rejected']} | {st['no_effect']} | {st['inconsistent']} |")
    add("")
    add(f"Denominators are all {design['n_trials_per_arm']} planned "
        f"lead-runs per arm: {design['n_leads']} leads x {design['runs']} "
        f"runs. They are lead-runs, not {design['n_trials_per_arm']} "
        "independent cases.")
    add("")

    if grade["comparisons"]:
        add("## Planned comparisons (paired per lead)")
        add("")
        add("| comparison | effect | leads where first arm is better | "
            "worse | tied | mean per-lead difference (points) | "
            "lead-run delta |")
        add("|---|---|---|---|---|---|---|")
        for c in grade["comparisons"]:
            add(f"| {c['a']} vs {c['b']} | {c['field']} | "
                f"{c['leads_a_better']}/{c['n_leads']} | "
                f"{c['leads_b_better']}/{c['n_leads']} | "
                f"{c['leads_tied']}/{c['n_leads']} | "
                f"{_points(c['mean_per_lead_difference'])} | "
                f"{c['lead_run_delta']:+d} "
                f"({c['a_lead_runs']['correct']} vs "
                f"{c['b_lead_runs']['correct']} of "
                f"{c['a_lead_runs']['n']}) |")
        add("")
        add("Each lead's share of correct runs in the first arm minus its "
            "share in the second; the unit is the lead. Descriptive "
            "only: no significance test, no p-value, no superiority "
            "claim.")
        add("")

    criteria = grade.get("criteria")
    if criteria:
        add("## Prespecified criteria")
        add("")
        add(f"Source: preregistration `{criteria['source']}`. "
            f"{criteria['note'][0].upper()}{criteria['note'][1:]}.")
        add("")
        for result in criteria.get("results", []):
            verdict = {True: "MET", False: "NOT MET",
                       None: "NOT EVALUABLE"}[result["met"]]
            add(f"### {result['id']}: {result['label']} - {verdict}")
            add("")
            for cond in result["conditions"]:
                add(f"- {_condition_text(cond)}")
            if result["met"] is not None:
                add(f"- reading fixed in advance: "
                    f"{result['if_met'] if result['met'] else result['if_not_met']}")
            add("")

    for arm, s in arms.items():
        add(f"## Arm: {arm}")
        add("")
        st = s["effect_status"]
        add(f"- planned lead-runs: {s['planned_trials']} "
            f"({s['independent_leads']} leads); delivered with a "
            f"consistent effect: {st['applied']}; rejected as "
            f"unparseable: {st['rejected']}; no effect recorded: "
            f"{st['no_effect']}; inconsistent: {st['inconsistent']}")
        add("")
        for field, label in (("tier", "Tier"), ("route", "Route")):
            add(f"### {label} effect accuracy by true segment")
            add("")
            add("| true segment | correct/n | accuracy |")
            add("|---|---|---|")
            data = s[f"{field}_effect"]
            for seg, d in data["by_segment"].items():
                add(f"| {seg} | {d['correct']}/{d['n']} | "
                    f"{_pct(d['accuracy'])} |")
            add(f"| **all** | {data['correct']}/{data['n']} | "
                f"{_pct(data['accuracy'])} |")
            add("")
        tg = s["tricky_gap"]
        add(f"Clean vs tricky (tier effect): clean "
            f"{_cn(tg['clean'])}, tricky {_cn(tg['tricky'])}.")
        add("")
        add("### Tier in the CRM vs true tier, most frequent first")
        add("")
        add("| true | in CRM | n |")
        add("|---|---|---|")
        for c in s["tier_confusion"]:
            add(f"| {c['true']} | {c['observed']} | {c['n']} |")
        add("")
        add("### Queue in the CRM vs true route, most frequent first")
        add("")
        add("| true | in CRM | n |")
        add("|---|---|---|")
        for c in s["route_confusion"]:
            add(f"| {c['true']} | {c['observed']} | {c['n']} |")
        add("")

    add("## Secondary: calibration of self-reported confidence")
    add("")
    add("Confidence comes from the decisions log (the qualifier's own "
        "statement); correctness comes from the world. The baseline arm "
        "always states 1.0.")
    add("")
    for arm, s in arms.items():
        cal = s["calibration"]
        if cal["ece"] is None:
            add(f"- {arm}: no lead-run reported a confidence "
                f"(0/{s['planned_trials']}).")
            add("")
            continue
        add(f"- {arm}: {_calibration_phrase(cal)}; "
            f"{cal['n_without_confidence']} lead-runs reported none and "
            "are not scored here (they are still failures above).")
        add("")
        add("| confidence bin | n | mean conf | tier effect accuracy |")
        add("|---|---|---|---|")
        for b in cal["bins"]:
            add(f"| {b['bin']} | {b['n']} | {b['mean_confidence']:.2f} | "
                f"{_pct(b['accuracy'])} |")
        add("")

    add("## Secondary: run-to-run stability")
    add("")
    for arm, s in arms.items():
        stab = s["stability"]
        add(f"### {arm}")
        add("")
        add("| run | tier effect | route effect |")
        add("|---|---|---|")
        for run_index, d in stab["by_run"].items():
            add(f"| {run_index} | {_cn(d['tier'])} | {_cn(d['route'])} |")
        add("")
        if stab["mean_per_lead_flip"] is not None:
            add(f"The tier in the CRM differs between runs for "
                f"{stab['leads_with_any_flip']}/"
                f"{stab['leads_with_multiple_runs']} leads (mean per-lead "
                f"flip rate {_pct(stab['mean_per_lead_flip'])}); tier "
                f"effect accuracy spread across runs: "
                f"{_pct(stab['tier_accuracy_spread'])}.")
            add("")

    diag = grade["self_report_diagnostics"]
    add("## Self-report log vs world")
    add("")
    add(f"Of {diag['n']} planned decisions: "
        f"{diag['log_parse_failures']} logged as unparseable; "
        f"{diag['claimed_but_not_delivered']} logged as decided but with "
        f"no consistent effect in the world; "
        f"{diag['delivered_differs_from_claim']} delivered differently "
        "from what the log claims. Informational: wherever the two "
        "disagree, the grade follows the world.")
    add("")

    add("## Limits")
    add("")
    add(f"- {design['n_leads']} synthetic leads x {design['runs']} "
        "repeats: repeated runs of one lead share its label and signals. "
        "Comparisons between arms are paired per lead for that reason.")
    add("- World-state grading checks that a decision was actually "
        "applied and where the lead ended up. In this harness the "
        "simulator applies accepted decisions faithfully, so it guards "
        "the measurement path (dropped, misapplied or misreported "
        "decisions); it does not make the dataset harder or the labels "
        "more realistic.")
    add("- The placebo arm uses one fixed seeded derangement. A different "
        "permutation gives a different placebo number; treat it as a "
        "sanity floor, not a precise estimate.")
    add("- Labels are hand-designed and unambiguous by construction. Real "
        "funnel data has contested labels, missing signals and drift; "
        "accuracy here is an upper bound, not a promise.")
    add("- The dataset is synthetic and shaped like a generic PLG "
        "free-to-paid motion. It is not any company's production data.")
    add("- Integrity checks and hashes are consistency checks on local "
        "files. They do not protect against the owner of those files.")
    add("- Every claim is about this prompt + this model + this dataset. "
        "Change any of the three and re-run before reusing a number.")
    add("")

    add("## How to reproduce this report (offline, no model calls)")
    add("")
    demo = (" --criteria-demo <prereg-manifest>"
            if criteria and not run["preregistered"] else "")
    add("```sh")
    add("python3 scripts/grade_world.py --run-dir <run-dir> "
        f"--data data/leads.jsonl{demo}")
    add("python3 scripts/world_report.py --run-dir <run-dir> "
        f"--data data/leads.jsonl{demo} --out <report.md>")
    add("```")
    add("")
    return "\n".join(L)
