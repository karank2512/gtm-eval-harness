#!/usr/bin/env python3
"""Regenerate REPORT.md from a v1 results JSONL file (v1 LEGACY grading).

No hand-typed numbers, and no wall-clock date: the same results file and
metadata always produce the same report. For v2 world-state reports use
scripts/world_report.py.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import report  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Regenerate REPORT.md (v1 legacy grading).")
    ap.add_argument("--results", required=True)
    ap.add_argument("--meta", default=None,
                    help="run metadata JSON (default: <results>.meta.json)")
    ap.add_argument("--out", default="REPORT.md")
    args = ap.parse_args()

    text = report.build_report(args.results, args.meta)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
