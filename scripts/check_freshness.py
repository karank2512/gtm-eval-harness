#!/usr/bin/env python3
"""Freshness check: are the tracked reports what their data regenerates?

Regenerates every tracked report from its tracked data and compares bytes.
No model calls, no network, no wall-clock dates.

- REPORT.md                       <- results/results.jsonl (real v1 run,
                                     v1 legacy grading)
- results/EXAMPLE-REPORT-mock.md  <- results/example-mock.jsonl (MOCK, v1
                                     legacy grading)
- results/v2-mock-example/        <- its sealed CRM world, re-graded
  grade.json and REPORT-MOCK.md      offline (MOCK, v2 world-state grading)
- the preregistration manifest    <- regenerated from the working tree,
                                     until the registered primary run
                                     exists; after that the pins are
                                     history and the registered run is
                                     re-graded instead (and REPORT-v2.md
                                     compared, if present)

Exit 0 if everything is fresh, 1 otherwise.
"""

from __future__ import annotations

import argparse
import difflib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from harness import prereg, report, world_grade, world_report  # noqa: E402
from harness.integrity import IntegrityError  # noqa: E402

LEGACY = [("results/results.jsonl", "REPORT.md"),
          ("results/example-mock.jsonl", "results/EXAMPLE-REPORT-mock.md")]
MOCK_WORLD = "results/v2-mock-example"
REGISTERED_REPORT = "REPORT-v2.md"


def _compare(root: str, rel: str, expected: str, stale: list) -> None:
    path = os.path.join(root, rel)
    if not os.path.isfile(path):
        stale.append(rel)
        print(f"STALE   {rel}: missing")
        return
    with open(path, "r", encoding="utf-8") as fh:
        actual = fh.read()
    if actual == expected:
        print(f"fresh   {rel}")
        return
    stale.append(rel)
    print(f"STALE   {rel}: differs from what its data regenerates")
    diff = difflib.unified_diff(actual.splitlines(), expected.splitlines(),
                                "tracked", "regenerated", lineterm="", n=0)
    for line in list(diff)[:40]:
        print("        " + line)


def check(root: str) -> list:
    stale: list = []
    cwd = os.getcwd()
    os.chdir(root)  # legacy metadata stores repo-relative result paths
    try:
        for results, target in LEGACY:
            try:
                expected = report.build_report(results)
            except (OSError, ValueError, KeyError) as exc:
                stale.append(target)
                print(f"STALE   {target}: cannot regenerate from "
                      f"{results}: {exc}")
                continue
            _compare(root, target, expected, stale)

        manifest = os.path.join(root, prereg.MANIFEST_PATH)
        try:
            grade = world_grade.grade_run(
                MOCK_WORLD, prereg.DATASET_PATH,
                criteria_demo_path=manifest)
            _compare(root, f"{MOCK_WORLD}/grade.json",
                     world_grade.dump_grade(grade), stale)
            _compare(root, f"{MOCK_WORLD}/REPORT-MOCK.md",
                     world_report.render(grade), stale)
        except IntegrityError as exc:
            stale.append(MOCK_WORLD)
            print(f"STALE   {MOCK_WORLD}: not gradeable: {exc}")

        primary = prereg.registered_primary_complete(root)
        if primary is None:
            problems = prereg.check_manifest(root)
            if problems:
                stale.append(prereg.MANIFEST_PATH)
                print(f"STALE   {'; '.join(problems)}")
            else:
                print(f"fresh   {prereg.MANIFEST_PATH} (registered run "
                      "not recorded yet: pins must match the source)")
        else:
            rel = os.path.relpath(primary, root)
            try:
                grade = world_grade.grade_run(
                    rel, prereg.DATASET_PATH, prereg_manifest_path=manifest)
                print(f"fresh   {rel} (registered run re-graded offline; "
                      "its receipt binds the preregistration manifest)")
                if os.path.isfile(os.path.join(root, REGISTERED_REPORT)):
                    _compare(root, REGISTERED_REPORT,
                             world_report.render(grade), stale)
            except IntegrityError as exc:
                stale.append(rel)
                print(f"STALE   {rel}: not gradeable: {exc}")
    finally:
        os.chdir(cwd)
    return stale


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=ROOT, help=argparse.SUPPRESS)
    args = ap.parse_args()
    stale = check(os.path.abspath(args.root))
    if stale:
        print(f"\n{len(stale)} stale artifact(s): regenerate them from "
              "their data with the commands in README.md; never edit a "
              "report by hand.")
        sys.exit(1)
    print("\nall tracked reports match their data")


if __name__ == "__main__":
    main()
