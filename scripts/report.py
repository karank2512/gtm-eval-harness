#!/usr/bin/env python3
"""Regenerate REPORT.md from a results JSONL file. No hand-typed numbers."""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import metrics, report  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Regenerate REPORT.md.")
    ap.add_argument("--results", required=True)
    ap.add_argument("--meta", default=None,
                    help="run metadata JSON (default: <results>.meta.json)")
    ap.add_argument("--out", default="REPORT.md")
    args = ap.parse_args()

    meta_path = args.meta or (args.results + ".meta.json")
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
    else:
        meta = {"results_path": args.results, "backend": "unknown"}
    meta.setdefault("results_path", args.results)
    meta["backend_name_for_cli"] = (
        "mock" if meta.get("backend") == "mock-test-only" else "claude-code")

    summary = metrics.summarize(args.results)
    text = report.render(summary, meta)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
