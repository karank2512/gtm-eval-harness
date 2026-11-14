#!/usr/bin/env python3
"""Preregistration tooling for the v2 run. No model calls.

    python3 scripts/prereg.py build     # (re)generate the manifest
    python3 scripts/prereg.py check     # manifest matches the working tree?
    python3 scripts/prereg.py verify    # full pre-run gate (needs the commit)
    python3 scripts/prereg.py plan --slot primary --out /tmp/plan.json

`verify` is the same gate run_world_eval.py --prereg applies before any
model call: the manifest must regenerate byte-identically, and the
manifest, the preregistration document, the dataset and every pinned
source file must be committed and unmodified.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from harness import prereg, world_runner  # noqa: E402
from harness.integrity import IntegrityError  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Preregistration tooling.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="write the manifest from the working tree")
    sub.add_parser("check", help="compare the manifest with the working "
                                 "tree (no git)")
    sub.add_parser("verify", help="full pre-run gate, including git")
    plan = sub.add_parser("plan", help="write the full expected trial plan")
    plan.add_argument("--slot", choices=sorted(prereg.SLOTS),
                      default="primary")
    plan.add_argument("--out", required=True)
    args = ap.parse_args()
    manifest_path = os.path.join(ROOT, prereg.MANIFEST_PATH)

    try:
        if args.cmd == "build":
            os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
            text = prereg.dump_manifest(prereg.build_manifest(ROOT))
            with open(manifest_path, "w", encoding="utf-8") as fh:
                fh.write(text)
            print(f"wrote {prereg.MANIFEST_PATH}")
        elif args.cmd == "check":
            problems = prereg.check_manifest(ROOT)
            if problems:
                print("STALE: " + "; ".join(problems), file=sys.stderr)
                sys.exit(1)
            print(f"{prereg.MANIFEST_PATH} matches the working tree")
        elif args.cmd == "verify":
            binding = prereg.verify_for_run(ROOT)
            print(json.dumps(binding, indent=2, sort_keys=True))
            print("preregistration gate passed: committed and unmodified "
                  f"at {binding['git_commit']}")
        else:
            plan_obj = prereg.slot_plan(ROOT, args.slot)
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(world_runner.dump_plan(plan_obj))
            print(f"wrote {args.out} "
                  f"(sha256 {world_runner.plan_sha256(plan_obj)})")
    except (prereg.PreregError, IntegrityError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
