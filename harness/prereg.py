"""Preregistration for the v2 world-state run: manifest and pre-run gates.

The machine-readable manifest is GENERATED from the specification in this
file plus hashes of the experiment inputs (dataset, source files, prompt
template, scorer, trial plan). It is deterministic: the same repository
contents always produce the same bytes.

Circularity is avoided the plain way: the manifest and the prose
preregistration document are NOT in the pinned source set (a file cannot
contain its own hash). Instead the run receipt records the sha256 and git
blob id of both, as committed, together with the commit they were
verified at.

verify_for_run() is the gate the runner calls before any model call. It
refuses to proceed unless the manifest regenerates byte-identically from
the working tree, and the manifest, the document, the dataset and every
pinned source file are committed and unmodified.

Honest boundary: a local git commit proves ordering only to the extent the
commit is published before the run; timestamps and hashes on one machine
are under its owner's control. This raises the cost of an accidental or
quiet change. It is not a notarisation.
"""

from __future__ import annotations

import datetime
import glob
import json
import os
import re
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from . import integrity, pipeline, world_runner

PREREG_ID = "gtm-v2-20261114"
MANIFEST_SCHEMA = "gtm-preregistration/1"
MANIFEST_PATH = f"docs/preregistrations/{PREREG_ID}.manifest.json"
DOC_PATH = f"docs/preregistrations/{PREREG_ID}.md"
DATASET_PATH = "data/leads.jsonl"
RESULTS_ROOT = f"results/v2/{PREREG_ID}"

ARMS = ["treatment", "placebo", "baseline"]
SEED = 20261114
BACKEND = {
    "backend": "claude-code",
    "model": "claude-fable-5-2",
    "disable_tools": True,
    "no_session_persistence": True,
    "extra_args": [],
    "timeout_s": 180,
    "cli_working_directory": "empty scratch directory",
}
SLOTS = {
    "primary": {"runs": 3, "limit": None, "dir_prefix": "attempt",
                "receipt_kind": "preregistered-primary"},
    "smoke": {"runs": 1, "limit": 12, "dir_prefix": "smoke",
              "receipt_kind": "preregistered-smoke"},
}

# Files outside harness/ that take part in running, grading or reporting
# the registered run. Every harness/*.py file is pinned automatically.
EXTRA_SOURCE_FILES = [
    "run_world_eval.py",
    "scripts/generate_leads.py",
    "scripts/grade_world.py",
    "scripts/prereg.py",
    "scripts/world_report.py",
]
SCORER_FILES = ["harness/integrity.py", "harness/world.py",
                "harness/world_grade.py"]

DECISION_CRITERIA = [
    {
        "id": "H1",
        "label": "Placebo control (validity gate)",
        "all_of": [
            {"metric": "tier_effect_accuracy", "arm": "placebo",
             "op": "<=", "value": "0.50"},
            {"metric": "tier_effect_accuracy_diff", "arm": "treatment",
             "vs": "placebo", "op": ">=", "value": "0.25"},
        ],
        "if_met": "The measurement responds to the leads' own signals; "
                  "the treatment figures are interpretable.",
        "if_not_met": "The measurement is declared invalid for this run: "
                      "no treatment or baseline-delta claim is made from "
                      "it.",
    },
    {
        "id": "H2",
        "label": "Tier effect near ceiling and above rules (v1 "
                 "replication)",
        "all_of": [
            {"metric": "tier_effect_accuracy", "arm": "treatment",
             "op": ">=", "value": "0.95"},
            {"metric": "tier_effect_accuracy_diff", "arm": "treatment",
             "vs": "baseline", "op": ">", "value": "0"},
        ],
        "if_met": "Replicates v1 under world-state grading: tier effects "
                  "are near ceiling on this dataset and above the rules "
                  "baseline.",
        "if_not_met": "v1's tier result did not replicate under "
                      "world-state grading; reported as a non-replication "
                      "with the observed counts.",
    },
    {
        "id": "H3",
        "label": "No practically meaningful routing advantage over rules "
                 "(v1 replication)",
        "all_of": [
            {"metric": "abs_route_effect_accuracy_diff", "arm": "treatment",
             "vs": "baseline", "op": "<=", "value": "0.05"},
        ],
        "if_met": "Replicates v1: the model's routing effect is within 5 "
                  "points of the free rules baseline on this dataset.",
        "if_not_met": "Does not replicate v1's routing finding; the "
                      "direction and size are reported as observed, with "
                      "no superiority claim in either direction.",
    },
    {
        "id": "H4",
        "label": "Every planned decision is delivered",
        "all_of": [
            {"metric": "undelivered_trials", "op": "==", "value": "0"},
        ],
        "if_met": "Every planned decision produced a consistent CRM "
                  "effect (tier, queue and dispatch receipt).",
        "if_not_met": "Some decisions produced no consistent CRM effect "
                      "(unparseable, dropped or inconsistent); they are "
                      "failures in every figure and are counted by kind.",
    },
]

SPEC: Dict[str, Any] = {
    "title": "GTM lead-qualification eval v2: world-state grading "
             "replication of v1",
    "registered_date": "2026-11-14",
    "disclosure": (
        "Not a held-out confirmatory study. The v1 run (same public "
        "synthetic dataset, same prompt, same model id) was completed and "
        "its results seen before this preregistration was written. v2 is "
        "an engineering replication under a stricter grading path; the "
        "criteria below were chosen with v1's numbers in view."),
    "units": {
        "independent_cases": "120 leads",
        "lead_runs_per_arm": "120 leads x 3 runs = 360",
        "model_calls": "treatment 360 + placebo 360 = 720 (baseline is "
                       "deterministic rules, 0 model calls)",
        "total_decisions": "3 arms x 360 = 1080",
        "note": "360 lead-runs per arm are NOT 360 independent cases; "
                "between-arm comparisons are paired per lead (n = 120).",
    },
    "metrics": {
        "primary": [
            {"name": "tier effect accuracy",
             "definition": "lead-runs whose CRM lead record carries the "
                           "true tier, confirmed by a matching dispatch "
                           "receipt",
             "denominator": "all planned lead-runs in the arm (360)"},
            {"name": "route effect accuracy",
             "definition": "lead-runs whose lead is a member of the true "
                           "route's queue, confirmed by a matching "
                           "dispatch receipt",
             "denominator": "all planned lead-runs in the arm (360)"},
        ],
        "failure_handling": "unparseable answers, dropped dispatches and "
                            "inconsistent effects stay in the denominator "
                            "as failures; none are excluded",
        "planned_comparisons": [
            "treatment vs baseline, tier and route: per-lead paired "
            "difference in share of correct runs (n = 120 leads): mean "
            "difference, leads better / worse / tied, lead-run delta",
            "treatment vs placebo, tier and route: same summary",
        ],
        "secondary": [
            "calibration of the model's self-reported confidence against "
            "tier effect correctness (ECE, Brier, direction); the "
            "confidence is a self-report taken from the decisions log",
            "run-to-run stability of the assigned tier (per-lead flip "
            "rate, per-run accuracy spread)",
            "clean vs tricky gap; tier and route confusions by segment",
        ],
        "inference": "descriptive only: no significance test, no p-value, "
                     "no superiority claim; thresholds are prespecified "
                     "descriptive criteria on a small synthetic dataset",
    },
    "stopping": {
        "rule": "the run aborts on the first CLI failure with no retries",
        "partial_output": "an aborted attempt keeps its .partial "
                          "directory, has no manifest, is never graded or "
                          "pooled, and is disclosed",
        "optional_stopping": "none: there is no interim look; an attempt "
                             "ends only by completing all 1080 planned "
                             "decisions or by a CLI failure",
        "restart": "after an aborted attempt, a fresh attempt may run the "
                   "full plan from the start in a new attempt directory; "
                   "the first COMPLETE attempt is the primary result and "
                   "no further attempts are made; each receipt lists all "
                   "earlier attempts",
    },
    "smoke": {
        "purpose": "pipeline health check (CLI reachable, answers "
                   "parseable) before the primary run",
        "design": "first 12 leads, 1 run, all three arms: 24 model calls, "
                  "36 decisions",
        "rules": "optional; completes at most once, before any primary "
                 "attempt (a smoke attempt aborted by a CLI failure may "
                 "be repeated and is disclosed); its numbers are outside "
                 "the primary counts and are never pooled; its 12 leads "
                 "are also in the primary run and this overlap is "
                 "disclosed; no pinned input may change between the "
                 "smoke and the primary run",
    },
    "deviations": "any change to a pinned input after registration "
                  "invalidates this preregistration for the run; it needs "
                  "a new preregistration id and commit, and the report "
                  "must say so",
}


class PreregError(RuntimeError):
    """A preregistration gate refused the run."""


# -------------------------------------------------------------- manifest

def source_files(root: str) -> List[str]:
    found = sorted(
        os.path.relpath(p, root).replace(os.sep, "/")
        for p in glob.glob(os.path.join(root, "harness", "*.py")))
    return sorted(set(found) | set(EXTRA_SOURCE_FILES))


def config_block() -> Dict[str, Any]:
    return {"arms": ARMS, "seed": SEED, "backend": BACKEND,
            "primary": {k: SLOTS["primary"][k] for k in ("runs", "limit")},
            "smoke": {k: SLOTS["smoke"][k] for k in ("runs", "limit")}}


def slot_plan(root: str, slot: str) -> Dict[str, Any]:
    """The full expected trial plan for the primary or smoke design."""
    data_path = os.path.join(root, DATASET_PATH)
    dataset = world_runner.load_dataset(data_path)
    return world_runner.build_plan(
        [r["id"] for r in dataset], integrity.sha256_file(data_path),
        ARMS, SLOTS[slot]["runs"], SEED, SLOTS[slot]["limit"])


def build_manifest(root: str) -> Dict[str, Any]:
    missing = [p for p in source_files(root) + [DATASET_PATH]
               if not os.path.isfile(os.path.join(root, p))]
    if missing:
        raise PreregError(f"experiment inputs missing: {missing}")
    pins = {p: integrity.sha256_file(os.path.join(root, p))
            for p in source_files(root)}
    design: Dict[str, Any] = {
        "dataset": {
            "path": DATASET_PATH,
            "sha256": integrity.sha256_file(
                os.path.join(root, DATASET_PATH)),
            "description": "synthetic PLG leads, seeded generator "
                           "(scripts/generate_leads.py --n 120 --seed "
                           "20261114); public, already used by v1",
        },
        "arms": ARMS,
        "seed": SEED,
        "backend": BACKEND,
        "results_root": RESULTS_ROOT,
    }
    for slot, spec in SLOTS.items():
        plan = slot_plan(root, slot)
        header = plan["header"]
        design[slot] = {
            "runs": spec["runs"], "limit": spec["limit"],
            "n_leads": header["n_leads"],
            "n_trials_per_arm": header["n_trials_per_arm"],
            "n_trials": header["n_trials"],
            "n_model_calls": header["n_model_calls"],
            "plan_sha256": world_runner.plan_sha256(plan),
            "inventory": {
                "arms": ARMS,
                "run_indexes": list(range(spec["runs"])),
                "lead_ids": header["lead_ids"],
                "trial_id_format": "<arm>/r<run_index>/<lead_id>",
                "worlds": len(ARMS) * spec["runs"],
            },
        }
    manifest = dict(SPEC)
    manifest.update({
        "schema": MANIFEST_SCHEMA,
        "id": PREREG_ID,
        "document": DOC_PATH,
        "design": design,
        "decision_criteria": DECISION_CRITERIA,
        "pins": {
            "source_files": pins,
            "source_set_sha256": integrity.combined_hash(pins),
            "prompt_template_sha256": integrity.sha256_text(
                pipeline.PROMPT_TEMPLATE),
            "scorer_files": SCORER_FILES,
            "scorer_sha256": integrity.combined_hash(
                {p: pins[p] for p in SCORER_FILES}),
            "config_sha256": integrity.sha256_canonical(config_block()),
            "excluded": "this manifest and everything under docs/ are "
                        "outside the pinned set; the run receipt binds "
                        "the committed manifest and document by sha256 "
                        "and git blob id instead",
        },
    })
    return manifest


def dump_manifest(manifest: Dict[str, Any]) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def _diff_paths(a: Any, b: Any, prefix: str = "") -> List[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out: List[str] = []
        for key in sorted(set(a) | set(b)):
            where = f"{prefix}.{key}" if prefix else str(key)
            if key not in a or key not in b:
                out.append(where)
            else:
                out += _diff_paths(a[key], b[key], where)
        return out
    return [] if a == b else [prefix]


def check_manifest(root: str, manifest_path: str = MANIFEST_PATH
                   ) -> List[str]:
    """Problems (empty = none) between the manifest on disk and the one
    the working tree generates. Pure file comparison, no git."""
    full = os.path.join(root, manifest_path)
    if not os.path.isfile(full):
        return [f"{manifest_path} does not exist"]
    with open(full, "r", encoding="utf-8") as fh:
        text = fh.read()
    expected = build_manifest(root)
    if text == dump_manifest(expected):
        return []
    try:
        actual = json.loads(text)
    except ValueError:
        return [f"{manifest_path} is not valid JSON"]
    paths = _diff_paths(expected, actual) or ["formatting"]
    return [f"{manifest_path} does not match the working tree at: "
            + ", ".join(paths[:12])]


# ------------------------------------------------------------- git gates

def _git(root: str, *args: str) -> str:
    try:
        proc = subprocess.run(["git", "-C", root] + list(args),
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PreregError(f"git {' '.join(args)} failed: {exc}") from exc
    if proc.returncode != 0:
        raise PreregError(
            f"git {' '.join(args)} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout


def _head_blobs(root: str) -> Dict[str, str]:
    blobs = {}
    for entry in _git(root, "ls-tree", "-r", "-z", "HEAD").split("\0"):
        if not entry:
            continue
        info, _, path = entry.partition("\t")
        parts = info.split()
        if len(parts) == 3 and parts[1] == "blob":
            blobs[path] = parts[2]
    return blobs


def verify_for_run(root: str, manifest_path: str = MANIFEST_PATH
                   ) -> Dict[str, Any]:
    """Every gate that must pass before a preregistered model call.

    Returns the binding recorded in the run receipt. Raises PreregError
    listing every failed gate otherwise.
    """
    root = os.path.realpath(root)
    here = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))
    if here != os.path.join(root, "harness"):
        raise PreregError(
            "the running harness code is not the repository being "
            "verified")
    if manifest_path != MANIFEST_PATH:
        raise PreregError(
            f"this code implements preregistration {PREREG_ID}; its "
            f"manifest is {MANIFEST_PATH}")
    top = os.path.realpath(_git(root, "rev-parse", "--show-toplevel").strip())
    if top != root:
        raise PreregError(f"{root} is not the top of a git work tree")
    commit = _git(root, "rev-parse", "HEAD").strip()
    # Committer time, normalised to UTC so it reads against the run's
    # own UTC timestamps.
    commit_time = datetime.datetime.fromtimestamp(
        int(_git(root, "show", "-s", "--format=%ct", "HEAD").strip()),
        datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    problems = check_manifest(root, manifest_path)
    with open(os.path.join(root, manifest_path), "rb") as fh:
        manifest_bytes = fh.read()
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except ValueError:
        raise PreregError("; ".join(problems))
    if manifest.get("id") != PREREG_ID:
        problems.append("manifest id does not match this code")

    guarded = sorted(set([manifest_path, DOC_PATH, DATASET_PATH]
                         + source_files(root)))
    blobs = _head_blobs(root)
    for rel in guarded:
        full = os.path.join(root, rel)
        if not os.path.isfile(full):
            problems.append(f"{rel}: missing")
            continue
        if rel not in blobs:
            problems.append(f"{rel}: not committed at HEAD")
            continue
        with open(full, "rb") as fh:
            if integrity.git_blob_sha1(fh.read()) != blobs[rel]:
                problems.append(f"{rel}: differs from the committed "
                                "version")
    dirty = _git(root, "status", "--porcelain", "--untracked-files=no",
                 "--", *guarded).strip()
    if dirty:
        problems.append("uncommitted changes to experiment inputs: "
                        + ", ".join(line[3:] for line in
                                    dirty.splitlines()))
    if problems:
        raise PreregError(
            "preregistration gate refused the run (no model call was "
            "made):\n  - " + "\n  - ".join(problems))

    with open(os.path.join(root, DOC_PATH), "rb") as fh:
        doc_bytes = fh.read()
    pins = manifest["pins"]
    return {
        "id": PREREG_ID,
        "git_commit": commit,
        "git_commit_time": commit_time,
        "manifest_path": manifest_path,
        "manifest_sha256": integrity.sha256_bytes(manifest_bytes),
        "manifest_git_blob": blobs[manifest_path],
        "document_path": DOC_PATH,
        "document_sha256": integrity.sha256_bytes(doc_bytes),
        "document_git_blob": blobs[DOC_PATH],
        "dataset_sha256": manifest["design"]["dataset"]["sha256"],
        "source_set_sha256": pins["source_set_sha256"],
        "prompt_template_sha256": pins["prompt_template_sha256"],
        "scorer_sha256": pins["scorer_sha256"],
        "config_sha256": pins["config_sha256"],
        "gates_passed": [
            "manifest regenerates byte-identically from the working tree "
            "(dataset, source, prompt, scorer, config and plan hashes)",
            "manifest, document, dataset and every pinned source file "
            "are committed at HEAD and unmodified",
            "no uncommitted changes to experiment inputs",
        ],
    }


# -------------------------------------------------------------- attempts

_ATTEMPT_RE = re.compile(r"^(attempt|smoke)-(\d{2})(\.partial)?$")


def scan_attempts(results_root: str) -> List[Dict[str, Any]]:
    """Every earlier attempt directory under the results root, with its
    state. Best-effort disclosure: it sees only what is still on disk."""
    found = []
    if not os.path.isdir(results_root):
        return found
    for name in sorted(os.listdir(results_root)):
        match = _ATTEMPT_RE.match(name)
        full = os.path.join(results_root, name)
        if not match or not os.path.isdir(full):
            continue
        state = "incomplete"
        if match.group(3) is None and os.path.isfile(
                os.path.join(full, world_runner.MANIFEST_FILE)):
            state = "complete"
        elif os.path.isfile(os.path.join(full, world_runner.ABORTED_FILE)):
            state = "aborted"
        receipt = os.path.join(full, world_runner.RECEIPT_FILE)
        found.append({
            "directory": name, "prefix": match.group(1),
            "index": int(match.group(2)), "state": state,
            "receipt_sha256": (integrity.sha256_file(receipt)
                               if os.path.isfile(receipt) else None)})
    return found


def next_run_dir(results_root: str, slot: str
                 ) -> Tuple[str, int, List[Dict[str, Any]]]:
    """Where the next attempt of this slot goes, enforcing the registered
    restart rules. Returns (run_dir, attempt_number, earlier_attempts)."""
    prefix = SLOTS[slot]["dir_prefix"]
    earlier = scan_attempts(results_root)
    primary = [a for a in earlier if a["prefix"] == "attempt"]
    smokes = [a for a in earlier if a["prefix"] == "smoke"]
    if any(a["state"] == "complete" for a in primary):
        raise PreregError(
            "a complete primary attempt already exists; the first "
            "complete attempt is final and no further attempts are made")
    if slot == "smoke":
        if primary:
            raise PreregError(
                "the smoke run must precede every primary attempt")
        if any(a["state"] == "complete" for a in smokes):
            raise PreregError(
                "a complete smoke run already exists; the smoke run is "
                "registered to complete at most once")
    same = primary if slot == "primary" else smokes
    number = max([a["index"] for a in same], default=0) + 1
    if number > 99:
        raise PreregError("too many attempts")
    disclosed = [{k: a[k] for k in ("directory", "state", "receipt_sha256")}
                 for a in earlier]
    return (os.path.join(results_root, f"{prefix}-{number:02d}"), number,
            disclosed)


def registered_primary_complete(root: str) -> Optional[str]:
    """Path of the completed registered primary run, if one exists."""
    results_root = os.path.join(root, RESULTS_ROOT)
    for attempt in scan_attempts(results_root):
        if attempt["prefix"] == "attempt" and attempt["state"] == "complete":
            return os.path.join(results_root, attempt["directory"])
    return None
