#!/usr/bin/env python3
"""Grade a completed v2 world run offline. No model calls.

Replays the grade from the persisted artifacts: the CRM world database,
the dataset's labels and the sealed trial plan. Refuses to produce a
score (exit 2) if the run is partial, aborted, or any artifact, hash or
inventory check fails.

    python3 scripts/grade_world.py --run-dir <run-dir> --out grade.json
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from harness import world_grade  # noqa: E402
from harness.integrity import IntegrityError  # noqa: E402


def add_grade_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--data", default=os.path.join(ROOT, "data",
                                                   "leads.jsonl"),
                    help="the labeled dataset the run was planned on")
    ap.add_argument("--prereg", default=None, metavar="MANIFEST",
                    help="preregistration manifest of a preregistered run "
                         "(default: the path named in the run receipt)")
    ap.add_argument("--criteria-demo", default=None, metavar="MANIFEST",
                    help="for a run that is NOT preregistered: apply this "
                         "manifest's criteria as a labeled format "
                         "demonstration")


def grade_from_args(args: argparse.Namespace):
    """Grade, resolving the preregistration manifest named in the receipt
    of a preregistered run. Exits 2 with the reason on any failure."""
    try:
        prereg_path = args.prereg
        if prereg_path is None:
            named = world_grade.receipt_prereg_path(args.run_dir)
            if named:
                prereg_path = os.path.join(ROOT, named)
        return world_grade.grade_run(args.run_dir, args.data,
                                     prereg_manifest_path=prereg_path,
                                     criteria_demo_path=args.criteria_demo)
    except IntegrityError as exc:
        print(f"NOT GRADED (failing closed): {exc}", file=sys.stderr)
        sys.exit(2)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Offline world-state grade of a completed v2 run.")
    add_grade_args(ap)
    ap.add_argument("--out", default=None, help="write the grade JSON here")
    args = ap.parse_args()
    grade = grade_from_args(args)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(world_grade.dump_grade(grade))
    label = " [MOCK - not a model result]" if grade["run"]["warning"] else ""
    print(f"graded {grade['design']['n_trials']} planned decisions from "
          f"the CRM world{label}; all integrity checks passed")
    for arm, s in grade["arms"].items():
        tier, route = s["tier_effect"], s["route_effect"]
        print(f"  {arm}: tier effect {tier['correct']}/{tier['n']}, "
              f"route effect {route['correct']}/{route['n']}, delivered "
              f"{s['effect_status']['applied']}/{s['planned_trials']}")
    if args.out:
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
