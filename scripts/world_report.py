#!/usr/bin/env python3
"""Regenerate a v2 world-state report from a completed run. No model calls.

The run is re-graded from its persisted world every time; a saved grade
file is never trusted. The report date is the run's recorded completion
time, so the output does not change from day to day.

    python3 scripts/world_report.py --run-dir <run-dir> --out REPORT-v2.md
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import world_report  # noqa: E402
from grade_world import add_grade_args, grade_from_args  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Regenerate a v2 world-state report.")
    add_grade_args(ap)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    text = world_report.render(grade_from_args(args))
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
