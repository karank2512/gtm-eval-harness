#!/usr/bin/env python3
"""Run the lead-qualification eval with v2 world-state grading.

Every decision is applied to a simulated CRM world (SQLite, owned by the
harness); correctness is decided later, offline, from that world by
scripts/grade_world.py. The output is a run DIRECTORY, never overwritten.

Mock (tests/CI; deterministic, NOT a model, no model calls):

    python3 run_world_eval.py --backend mock --run-dir /tmp/world-mock

Preregistered real run (720 model calls through the Claude Code CLI on
this machine's subscription). Refuses to start unless the preregistration
is committed and every pinned input is unmodified:

    python3 scripts/prereg.py verify
    python3 run_world_eval.py --prereg \
        docs/preregistrations/gtm-v2-20261114.manifest.json

The v1 runner (run_eval.py) is kept unchanged in behavior for reproducing
v1 legacy-graded results.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from harness import integrity, prereg, runner, world_runner  # noqa: E402
from harness.backends import (BackendError, ClaudeCodeBackend,  # noqa: E402
                              MockBackend)

EXIT_CLI_FAILURE = 1
EXIT_REFUSED = 2
_DESIGN_FLAGS = ("backend", "model", "data", "arms", "runs", "limit",
                 "seed", "extra_args", "run_dir")


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Run the eval with v2 world-state grading.")
    ap.add_argument("--prereg", default=None, metavar="MANIFEST",
                    help="run the preregistered design in this manifest; "
                         "every design flag is then fixed by the manifest")
    ap.add_argument("--smoke", action="store_true",
                    help="with --prereg: run the registered 12-lead smoke "
                         "design instead of the primary run")
    ap.add_argument("--results-root", default=None,
                    help="with --prereg: parent directory for attempt "
                         "directories (default: the registered one)")
    ap.add_argument("--command", default="claude",
                    help="path to the Claude Code CLI")
    ap.add_argument("--backend", choices=["claude-code", "mock"],
                    default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--exploratory-unregistered", action="store_true",
                    help="required to use the claude-code backend without "
                         "--prereg; the run is labeled not preregistered")
    ap.add_argument("--data", default=None)
    ap.add_argument("--arms", default=None)
    ap.add_argument("--runs", type=int, default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--extra-args", default=None,
                    help="extra flags passed verbatim to the Claude Code "
                         "CLI (not allowed with --prereg)")
    ap.add_argument("--run-dir", default=None,
                    help="run directory to create (must not exist)")
    return ap


def _real_backend(model, command, extra_args, scratch):
    return ClaudeCodeBackend(model=model, command=command,
                             timeout_s=prereg.BACKEND["timeout_s"],
                             extra_args=extra_args, cwd=scratch)


def _prepare_prereg(args, ap, scratch):
    set_flags = [f for f in _DESIGN_FLAGS if getattr(args, f) is not None]
    if set_flags or args.exploratory_unregistered:
        ap.error("--prereg fixes the design; do not pass: "
                 + ", ".join("--" + f.replace("_", "-") for f in set_flags))
    slot = "smoke" if args.smoke else "primary"
    manifest_path = os.path.relpath(
        os.path.realpath(args.prereg), os.path.realpath(ROOT)
    ).replace(os.sep, "/")
    # Gate first: nothing below runs unless the preregistration is
    # committed and every pinned input matches it.
    binding = prereg.verify_for_run(ROOT, manifest_path)
    with open(os.path.join(ROOT, manifest_path), "r",
              encoding="utf-8") as fh:
        manifest = json.load(fh)
    results_root = args.results_root or os.path.join(
        ROOT, manifest["design"]["results_root"])
    run_dir, attempt, earlier = prereg.next_run_dir(results_root, slot)
    data_path = os.path.join(ROOT, manifest["design"]["dataset"]["path"])
    plan = prereg.slot_plan(ROOT, slot)
    if (world_runner.plan_sha256(plan)
            != manifest["design"][slot]["plan_sha256"]):
        raise prereg.PreregError("trial plan does not match the manifest")
    backend = _real_backend(prereg.BACKEND["model"], args.command, [],
                            scratch)
    described = world_runner.public_backend_detail(backend)
    described.pop("launcher", None)
    if described != prereg.BACKEND:
        raise prereg.PreregError(
            f"backend configuration {described} is not the registered "
            f"one {prereg.BACKEND}")
    binding.update({
        "slot": slot, "attempt": attempt, "earlier_attempts": earlier,
        "results_root": ("registered" if args.results_root is None
                         else "overridden on the command line")})
    receipt = world_runner.make_receipt(
        prereg.SLOTS[slot]["receipt_kind"], plan, backend,
        preregistration=binding)
    return data_path, plan, backend, run_dir, receipt


def _prepare_adhoc(args, ap, scratch):
    if args.smoke or args.results_root:
        ap.error("--smoke and --results-root only apply with --prereg")
    if not args.run_dir:
        ap.error("--run-dir is required")
    backend_name = args.backend or "mock"
    data_path = args.data or os.path.join(ROOT, "data", "leads.jsonl")
    arms = [a.strip() for a in (args.arms or ",".join(runner.ARMS)
                                ).split(",") if a.strip()]
    for arm in arms:
        if arm not in runner.ARMS:
            ap.error(f"unknown arm: {arm}")
    seed = args.seed if args.seed is not None else prereg.SEED
    runs = args.runs if args.runs is not None else 3
    dataset = world_runner.load_dataset(data_path)
    plan = world_runner.build_plan(
        [r["id"] for r in dataset], integrity.sha256_file(data_path),
        arms, runs, seed, args.limit)
    if backend_name == "mock":
        if args.model or args.extra_args:
            ap.error("--model/--extra-args do not apply to the mock "
                     "backend")
        backend = MockBackend(seed=seed)
        kind = "mock"
    else:
        if not args.exploratory_unregistered:
            ap.error("a real-model world run is either preregistered "
                     "(--prereg MANIFEST) or explicitly exploratory "
                     "(--exploratory-unregistered)")
        backend = _real_backend(args.model, args.command,
                                shlex.split(args.extra_args or ""), scratch)
        kind = "exploratory"
    receipt = world_runner.make_receipt(kind, plan, backend)
    return data_path, plan, backend, args.run_dir, receipt


def main() -> None:
    ap = _parser()
    args = ap.parse_args()
    # Real CLI calls start from an empty scratch directory, so nothing in
    # this repository (dataset, labels, world database) is in the CLI's
    # working directory.
    scratch = tempfile.mkdtemp(prefix="gtm-eval-cli-")
    try:
        try:
            prepare = _prepare_prereg if args.prereg else _prepare_adhoc
            data_path, plan, backend, run_dir, receipt = prepare(
                args, ap, scratch)
            # From here on the runner works with the model-facing view
            # only: truth labels are dropped before the first trial.
            leads = world_runner.model_facing(
                world_runner.load_dataset(data_path))
            manifest = world_runner.run_world(leads, plan, backend, run_dir,
                                              receipt)
        except BackendError as exc:
            print(f"run aborted on the first CLI failure: {exc}\n"
                  "the partial run directory (if any) is preserved with "
                  "an ABORTED.json and no manifest; it is not gradeable "
                  "and no completed run was touched.", file=sys.stderr)
            sys.exit(EXIT_CLI_FAILURE)
        except (prereg.PreregError, world_runner.RunDirError,
                integrity.IntegrityError) as exc:
            print(f"refused: {exc}", file=sys.stderr)
            sys.exit(EXIT_REFUSED)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print(json.dumps({
        "run_dir": run_dir, "state": manifest["state"],
        "kind": manifest["kind"], "counts": manifest["counts"],
        "next": [
            f"python3 scripts/grade_world.py --run-dir {run_dir}",
            f"python3 scripts/world_report.py --run-dir {run_dir} "
            "--out <report.md>"],
    }, indent=2))


if __name__ == "__main__":
    main()
