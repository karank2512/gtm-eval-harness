import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import runner  # noqa: E402
from harness.backends import (BackendError, BackendResponse,  # noqa: E402
                              ClaudeCodeBackend, MockBackend)
from scripts.generate_leads import generate  # noqa: E402


def _backend() -> ClaudeCodeBackend:
    with mock.patch("harness.backends.shutil.which", return_value="/usr/bin/claude"):
        return ClaudeCodeBackend(model="m")


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


class TestCliFailuresRaise(unittest.TestCase):
    """Behavior 1+2: zero retries; immediate raise on timeout, nonzero
    exit, or an is_error envelope."""

    def test_nonzero_exit_raises_once_no_retry(self):
        backend = _backend()
        with mock.patch("harness.backends.subprocess.run",
                        return_value=_completed(1, stderr="boom")) as run:
            with self.assertRaises(BackendError):
                backend.qualify("prompt")
        self.assertEqual(run.call_count, 1)

    def test_timeout_raises_once_no_retry(self):
        backend = _backend()
        with mock.patch("harness.backends.subprocess.run",
                        side_effect=subprocess.TimeoutExpired("claude", 180)) as run:
            with self.assertRaises(BackendError):
                backend.qualify("prompt")
        self.assertEqual(run.call_count, 1)

    def test_is_error_envelope_raises_despite_exit_0(self):
        backend = _backend()
        envelope = json.dumps({"is_error": True, "result": "rate limited"})
        with mock.patch("harness.backends.subprocess.run",
                        return_value=_completed(0, stdout=envelope)):
            with self.assertRaises(BackendError) as ctx:
                backend.qualify("prompt")
        self.assertIn("error envelope", str(ctx.exception))

    def test_success_envelope_unwraps_result(self):
        backend = _backend()
        answer = json.dumps({"tier": "team", "route": "sales_assist",
                             "confidence": 0.7, "reason": "x"})
        envelope = json.dumps({"is_error": False, "result": answer})
        with mock.patch("harness.backends.subprocess.run",
                        return_value=_completed(0, stdout=envelope)):
            resp = backend.qualify("prompt")
        self.assertIsNotNone(resp.call)
        self.assertEqual(resp.call.tier, "team")


class _RaisesOnNthCall(MockBackend):
    def __init__(self, n):
        super().__init__()
        self.n = n
        self.calls = 0

    def qualify(self, prompt, run_index=0):
        self.calls += 1
        if self.calls == self.n:
            raise BackendError("claude CLI exit 1: signed out")
        return super().qualify(prompt, run_index=run_index)


class _AllParseFail(MockBackend):
    def qualify(self, prompt, run_index=0):
        return BackendResponse(raw_text="not json", call=None,
                               error="parse: no JSON object")


class TestRunnerFailFast(unittest.TestCase):
    """Behavior 3+4: abort on the FIRST CLI failure (parse failures stay
    metric rows); partial output and previous complete file preserved."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data_path = os.path.join(self.tmp, "leads.jsonl")
        with open(self.data_path, "w", encoding="utf-8") as fh:
            for lead in generate(n=10, seed=4):
                fh.write(json.dumps(asdict(lead), sort_keys=True) + "\n")
        self.leads = runner.load_leads(self.data_path)
        self.out = os.path.join(self.tmp, "results.jsonl")

    def test_aborts_on_first_cli_failure(self):
        backend = _RaisesOnNthCall(3)
        with self.assertRaises(BackendError):
            runner.run_all(self.leads, backend, ["treatment"],
                           runs=1, seed=4, out_path=self.out)
        self.assertEqual(backend.calls, 3)  # stopped at the failure, not later
        self.assertFalse(os.path.exists(self.out))  # no fake complete file

    def test_abort_preserves_partial_and_previous_complete(self):
        with open(self.out, "w", encoding="utf-8") as fh:
            fh.write('{"previous": "complete"}\n')
        backend = _RaisesOnNthCall(4)
        with self.assertRaises(BackendError):
            runner.run_all(self.leads, backend, ["treatment"],
                           runs=1, seed=4, out_path=self.out)
        with open(self.out, "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), '{"previous": "complete"}\n')
        partial = self.out + ".partial"
        self.assertTrue(os.path.exists(partial))
        with open(partial, "r", encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        self.assertEqual(len(rows), 3)  # everything before the failure kept
        self.assertTrue(all(r["parse_ok"] for r in rows))

    def test_parse_failures_are_rows_not_aborts(self):
        counts = runner.run_all(self.leads, _AllParseFail(), ["treatment"],
                                runs=1, seed=4, out_path=self.out)
        self.assertEqual(counts["treatment"], 10)
        with open(self.out, "r", encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        self.assertEqual(len(rows), 10)
        self.assertTrue(all(not r["parse_ok"] for r in rows))
        self.assertTrue(all(r["error"].startswith("parse:") for r in rows))

    def test_successful_run_replaces_output_atomically(self):
        counts = runner.run_all(self.leads, MockBackend(), ["treatment"],
                                runs=1, seed=4, out_path=self.out)
        self.assertEqual(counts["treatment"], 10)
        self.assertTrue(os.path.exists(self.out))
        self.assertFalse(os.path.exists(self.out + ".partial"))


if __name__ == "__main__":
    unittest.main()
