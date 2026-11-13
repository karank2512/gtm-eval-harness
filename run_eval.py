#!/usr/bin/env python3
"""Run the lead-qualification eval.

Real runs use the Claude Code CLI on this machine (subscription, no API key):

    python3 run_eval.py --backend claude-code --model <model> --runs 3 \
        --out results/results.jsonl

Tests/CI use the mock backend (deterministic, NOT a model):

    python3 run_eval.py --backend mock --runs 2 --limit 24 \
        --out results/example-mock.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import runner  # noqa: E402
from harness.backends import ClaudeCodeBackend, MockBackend  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the lead-qualification eval.")
    ap.add_argument("--data", default="data/leads.jsonl")
    ap.add_argument("--backend", choices=["claude-code", "mock"],
                    default="claude-code")
    ap.add_argument("--model", default=None,
                    help="model name for the claude-code backend "
                         "(default: the CLI's configured model)")
    ap.add_argument("--command", default="claude",
                    help="path to the Claude Code CLI")
    ap.add_argument("--arms", default="treatment,placebo,baseline")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--limit", type=int, default=None,
                    help="only the first N leads (smoke runs)")
    ap.add_argument("--seed", type=int, default=20261114)
    ap.add_argument("--sleep", type=float, default=0.0,
                    help="seconds to sleep between model calls")
    ap.add_argument("--out", required=True)
    ap.add_argument("--meta-out", default=None,
                    help="write run metadata JSON here "
                         "(default: <out>.meta.json)")
    args = ap.parse_args()

    leads = runner.load_leads(args.data)
    if args.backend == "mock":
        backend = MockBackend(seed=args.seed)
        warning = ("MOCK BACKEND: deterministic test double, not a language "
                   "model. These numbers check harness math only.")
    else:
        backend = ClaudeCodeBackend(model=args.model, command=args.command)
        warning = None

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    for arm in arms:
        if arm not in runner.ARMS:
            ap.error(f"unknown arm: {arm}")

    counts = runner.run_all(leads, backend, arms, args.runs, args.seed,
                            args.out, limit=args.limit)

    meta = {
        "backend": backend.name,
        "model": args.model,
        "n_leads": min(args.limit, len(leads)) if args.limit else len(leads),
        "seed": args.seed,
        "runs": args.runs,
        "arms": arms,
        "results_path": args.out,
        "warning": warning,
        "backend_detail": backend.describe(),
    }
    meta_path = args.meta_out or (args.out + ".meta.json")
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, sort_keys=True)
    print(json.dumps({"counts": counts, "meta": meta_path}, indent=2))


if __name__ == "__main__":
    main()
