"""Shared helpers for the v2 world tests. Not a test module.

Nothing here calls a model. Real-CLI code paths are exercised with a fake
`claude` shell script that returns a fixed answer.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
from dataclasses import asdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from harness import integrity, pipeline, world_runner  # noqa: E402
from harness.backends import (BackendError, BackendResponse,  # noqa: E402
                              MockBackend)
from scripts.generate_leads import generate  # noqa: E402

ARMS = ["treatment", "placebo", "baseline"]
FIXED_CLOCK = "2020-01-02T03:04:05Z"


def write_dataset(tmp: str, n: int = 12, seed: int = 4,
                  name: str = "leads.jsonl") -> str:
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        for lead in generate(n=n, seed=seed):
            fh.write(json.dumps(asdict(lead), sort_keys=True) + "\n")
    return path


class OracleBackend:
    """Answers with the truth label of whichever lead the prompt shows.
    A test double: lets tests start from a world that should be 100%
    correct and then break one thing at a time."""

    name = "oracle-test-only"

    def __init__(self, dataset, confidence: float = 0.9):
        self.answers = {pipeline.build_prompt(row): row["truth"]
                        for row in dataset}
        self.confidence = confidence
        self.calls = 0

    def describe(self):
        return {"backend": self.name}

    def qualify(self, prompt, run_index=0):
        self.calls += 1
        truth = self.answers[prompt]
        call = pipeline.QualificationCall(
            tier=truth["tier"], route=truth["route"],
            confidence=self.confidence, reason="oracle: definitely right")
        return BackendResponse(raw_text=json.dumps(asdict(call)), call=call)


class RaisesOnNthCall(MockBackend):
    def __init__(self, n, seed=7):
        super().__init__(seed=seed)
        self.n = n
        self.calls = 0

    def qualify(self, prompt, run_index=0):
        self.calls += 1
        if self.calls == self.n:
            raise BackendError("claude CLI exit 1: signed out")
        return super().qualify(prompt, run_index=run_index)


class ParseFailEvery(MockBackend):
    """Every k-th answer is unparseable (k=1: all of them)."""

    def __init__(self, k, seed=7):
        super().__init__(seed=seed)
        self.k = k
        self.calls = 0

    def qualify(self, prompt, run_index=0):
        self.calls += 1
        if self.calls % self.k == 0:
            return BackendResponse(raw_text="I think it is a team lead.",
                                   call=None,
                                   error="parse: no JSON object")
        return super().qualify(prompt, run_index=run_index)


def do_run(tmp: str, data_path: str, name: str = "run", backend=None,
           arms=None, runs: int = 2, seed: int = 11, limit=None,
           port_wrapper=None, leads=None, kind: str = "mock") -> str:
    """Run a plan into <tmp>/<name>; returns the run directory."""
    dataset = world_runner.load_dataset(data_path)
    plan = world_runner.build_plan(
        [r["id"] for r in dataset], integrity.sha256_file(data_path),
        arms or ARMS, runs, seed, limit)
    backend = backend or MockBackend(seed=seed)
    receipt = world_runner.make_receipt(kind, plan, backend,
                                        started_at_utc=FIXED_CLOCK)
    run_dir = os.path.join(tmp, name)
    world_runner.run_world(
        leads if leads is not None else world_runner.model_facing(dataset),
        plan, backend, run_dir, receipt, port_wrapper=port_wrapper,
        clock=lambda: FIXED_CLOCK)
    return run_dir


def make_writable(run_dir: str) -> None:
    for name in os.listdir(run_dir):
        os.chmod(os.path.join(run_dir, name),
                 stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)


def reseal(run_dir: str) -> None:
    """Recompute the manifest's file hashes and seal after an edit: what
    an owner of the files could do. Tests use it to show which edits the
    grader still catches (or ignores) when the hashes have been redone."""
    make_writable(run_dir)
    path = os.path.join(run_dir, world_runner.MANIFEST_FILE)
    with open(path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    for name in world_runner.SEALED_FILES:
        manifest["artifacts"][name] = integrity.sha256_file(
            os.path.join(run_dir, name))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(world_runner.seal_manifest(manifest), fh, indent=2,
                  sort_keys=True)
        fh.write("\n")


def edit_world(run_dir: str, statements, resealed: bool = True,
               ignore_checks: bool = False) -> None:
    """Run raw SQL against a sealed world, then optionally reseal."""
    make_writable(run_dir)
    conn = sqlite3.connect(os.path.join(run_dir, world_runner.WORLD_FILE))
    if ignore_checks:
        conn.execute("PRAGMA ignore_check_constraints = ON")
    with conn:
        for statement in statements:
            if isinstance(statement, str):
                conn.execute(statement)
            else:
                conn.execute(*statement)
    conn.close()
    if resealed:
        reseal(run_dir)


def edit_decisions(run_dir: str, fn, resealed: bool = True) -> None:
    """Rewrite the decisions log through fn(rows) -> rows."""
    make_writable(run_dir)
    path = os.path.join(run_dir, world_runner.DECISIONS_FILE)
    rows = integrity.load_jsonl(path)
    rows = fn(rows)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    if resealed:
        reseal(run_dir)


def dir_digest(path: str) -> dict:
    return {name: integrity.sha256_file(os.path.join(path, name))
            for name in sorted(os.listdir(path))}


FAKE_ANSWER = json.dumps({"tier": "team", "route": "sales_assist",
                          "confidence": 0.7, "reason": "fake"})


def write_fake_claude(tmp: str, fail_at: int = 0,
                      name: str = "fake-claude") -> tuple:
    """A stand-in for the Claude Code CLI: NOT a model. Logs its argv and
    working directory, then prints a fixed answer in the CLI's JSON
    envelope. With fail_at=N the N-th call exits 1 instead."""
    script = os.path.join(tmp, name)
    log = os.path.join(tmp, name + ".log")
    envelope = json.dumps({"is_error": False, "result": FAKE_ANSWER,
                           "modelUsage": {"claude-fable-5-2": {}}})
    lines = [
        "#!/bin/sh",
        "while IFS= read -r _line; do :; done",
        f'echo "$*|$PWD|$(echo *)" >> "{log}"',
    ]
    if fail_at:
        lines += [
            f'n=$(wc -l < "{log}")',
            f'if [ "$n" -eq {fail_at} ]; then',
            '  echo "signed out" >&2; exit 1',
            "fi",
        ]
    lines.append(f"cat <<'FAKE_EOF'\n{envelope}\nFAKE_EOF")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(script, 0o755)
    return script, log


def fake_calls(log: str) -> list:
    if not os.path.exists(log):
        return []
    with open(log, "r", encoding="utf-8") as fh:
        return [line.rstrip("\n") for line in fh if line.strip()]


REPO_FILES = ["run_world_eval.py", "run_eval.py"]
REPO_DIRS = ["harness", "scripts", "data", "docs"]


def git(repo: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", repo, "-c", "user.name=Test",
         "-c", "user.email=test@example.invalid",
         "-c", "commit.gpgsign=false"] + list(args),
        check=True, capture_output=True, text=True)


def make_repo(dest: str) -> str:
    """A throwaway git repository holding a copy of the harness, with a
    freshly generated preregistration manifest, all committed."""
    os.makedirs(dest)
    for name in REPO_FILES:
        shutil.copy(os.path.join(ROOT, name), os.path.join(dest, name))
    for name in REPO_DIRS:
        shutil.copytree(os.path.join(ROOT, name), os.path.join(dest, name),
                        ignore=shutil.ignore_patterns("__pycache__"))
    run_script(dest, "scripts/prereg.py", "build")
    git(dest, "init", "-q")
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "register")
    return dest


def run_script(repo: str, script: str, *args: str,
               check: bool = True) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run(
        [sys.executable, os.path.join(repo, script)] + list(args),
        cwd=repo, capture_output=True, text=True, env=env)
    if check and proc.returncode != 0:
        raise AssertionError(
            f"{script} {' '.join(args)} failed ({proc.returncode}):\n"
            f"{proc.stdout}\n{proc.stderr}")
    return proc
