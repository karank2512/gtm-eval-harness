"""Model backends.

Two ways to make qualification calls:

- ClaudeCodeBackend: drives the local Claude Code CLI (`claude -p`) so runs
  execute on the user's Claude subscription with no API key and no usage
  billing. This is the backend for real measured runs.
- MockBackend: a deterministic heuristic with seeded noise. NOT a language
  model. Exists so tests and CI can verify harness math end to end. Its
  results must never be presented as model measurements.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
import zlib
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .pipeline import QualificationCall, parse_response


class BackendError(RuntimeError):
    pass


@dataclass
class BackendResponse:
    raw_text: str
    call: Optional[QualificationCall]
    error: Optional[str] = None


class ClaudeCodeBackend:
    """Runs each qualification prompt through the local Claude Code CLI.

    Requires `claude` on PATH and an authenticated Claude Code install
    (subscription sign-in). No API key is used or accepted.
    """

    name = "claude-code"

    def __init__(self, model: Optional[str] = None, command: str = "claude",
                 timeout_s: int = 180,
                 extra_args: Optional[list] = None,
                 disable_tools: bool = True,
                 no_session_persistence: bool = True):
        self.model = model
        self.command = command
        self.timeout_s = timeout_s
        self.extra_args = list(extra_args or [])
        # Harness semantics: every qualification call is a stateless,
        # tool-free prompt -> JSON completion. These are on by default so
        # a fresh checkout reproduces published numbers exactly.
        self.disable_tools = disable_tools
        self.no_session_persistence = no_session_persistence
        if shutil.which(command) is None:
            raise BackendError(
                f"{command!r} not found on PATH. Install/sign in to Claude "
                "Code on this machine first (subscription, not API key).")

    def describe(self) -> Dict[str, Any]:
        return {"backend": self.name, "model": self.model or "cli-default",
                "command": self.command,
                "disable_tools": self.disable_tools,
                "no_session_persistence": self.no_session_persistence}

    def qualify(self, prompt: str, run_index: int = 0) -> BackendResponse:
        """One call, one attempt. CLI failures raise BackendError
        immediately (timeout, nonzero exit, or an is_error envelope) -
        retrying would turn a broken setup into a slow expensive one.
        Only an unparseable model answer comes back as an error row."""
        argv = [self.command, "-p", "--output-format", "json"]
        if self.model:
            argv += ["--model", self.model]
        if self.disable_tools:
            argv += ["--tools", ""]
        if self.no_session_persistence:
            argv += ["--no-session-persistence"]
        argv += self.extra_args
        try:
            proc = subprocess.run(
                argv, input=prompt, capture_output=True, text=True,
                timeout=self.timeout_s)
        except subprocess.TimeoutExpired as exc:
            raise BackendError(
                f"claude CLI timed out after {self.timeout_s}s") from exc
        if proc.returncode != 0:
            raise BackendError(
                f"claude CLI exit {proc.returncode}: {proc.stderr[:300]}")
        text = self._extract_text(proc.stdout)
        try:
            return BackendResponse(raw_text=text, call=parse_response(text))
        except ValueError as exc:
            return BackendResponse(raw_text=text, call=None,
                                   error=f"parse: {exc}")

    @staticmethod
    def _extract_text(raw: str) -> str:
        """Claude Code's --output-format json wraps the reply; unwrap it.
        An is_error envelope means the CLI itself failed (exit code can
        still be 0), so it raises like any other CLI failure."""
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        if isinstance(obj, dict):
            if obj.get("is_error"):
                raise BackendError(
                    f"claude CLI returned an error envelope: "
                    f"{str(obj.get('result'))[:300]}")
            if isinstance(obj.get("result"), str):
                return obj["result"]
        return raw


class MockBackend:
    """Deterministic stand-in for tests/CI. NOT a language model.

    Heuristic with realistic blind spots (over-weights employer size, reads
    low usage as low fit) plus per-run seeded noise, so harness math can be
    checked against plausible-but-known behavior.
    """

    name = "mock-test-only"

    def __init__(self, seed: int = 7, noise: float = 0.12):
        self.seed = seed
        self.noise = noise

    def describe(self) -> Dict[str, Any]:
        return {"backend": self.name, "seed": self.seed, "noise": self.noise,
                "warning": "deterministic test double, not a model"}

    def qualify(self, prompt: str, run_index: int = 0) -> BackendResponse:
        # The mock parses the rendered lead block back out of the prompt, the
        # same fields the pipeline put in.
        fields: Dict[str, str] = {}
        in_lead = False
        for line in prompt.splitlines():
            if line.strip() == "Lead:":
                in_lead = True
                continue
            if in_lead and ":" in line:
                key, _, value = line.partition(":")
                fields[key.strip()] = value.strip()
        employees = int(fields.get("employees", "0"))
        seats = int(fields.get("seats_active", "0"))
        devices = int(fields.get("devices", "0"))
        asked_pricing = fields.get("asked_about_pricing") == "True"
        domain_claimed = fields.get("domain_claimed") == "True"
        features = fields.get("features_used", "")
        enterprise_feats = any(f in features for f in
                               ("sso_saml", "scim_provisioning",
                                "custom_retention", "dlp_controls"))
        invited = int(fields.get("invited_teammates", "0"))

        # Heuristic with known blind spots.
        if employees >= 1000 and seats > 10:
            tier, confidence = "enterprise", 0.85
        elif employees >= 1000:
            tier, confidence = "personal_dev", 0.55
        elif seats <= 2 and invited == 0 and not asked_pricing:
            tier, confidence = "personal_dev", 0.8
        elif asked_pricing or domain_claimed or enterprise_feats:
            tier, confidence = "enterprise", 0.7
        else:
            tier, confidence = "team", 0.65

        rng = random.Random(
            f"{self.seed}:{run_index}:{zlib.crc32(prompt.encode())}")
        if rng.random() < self.noise:
            tier = rng.choice([t for t in
                               ("personal_dev", "team", "enterprise")
                               if t != tier])
            confidence = max(0.3, confidence - 0.25)

        route = {"enterprise": "sales", "team": "sales_assist",
                 "personal_dev": "self_serve"}[tier]
        call = QualificationCall(tier=tier, route=route,
                                 confidence=confidence,
                                 reason="mock heuristic")
        raw = json.dumps({"tier": call.tier, "route": call.route,
                          "confidence": call.confidence,
                          "reason": call.reason})
        return BackendResponse(raw_text=raw, call=call)
