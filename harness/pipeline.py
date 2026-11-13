"""The lead-qualification pipeline under test.

This is the thing a GTM team ships: a prompt that turns raw lead signals into
a tier, a routing decision, and a confidence. The harness measures whether
those calls are any good - the pipeline itself is deliberately ordinary.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict

TIERS = ["personal_dev", "team", "enterprise"]
ROUTES = ["self_serve", "sales_assist", "sales"]

PROMPT_TEMPLATE = """You are the lead-qualification step of a PLG (product-led growth) funnel \
for a SaaS product with a free plan, a team tier, and an enterprise tier.

Given one signup lead, decide:
- tier: one of "personal_dev" (an individual using the product for themselves), \
"team" (a team at a small or mid-size company), or "enterprise" (a large company \
with enterprise procurement signals)
- route: one of "self_serve" (leave in the self-serve funnel), "sales_assist" \
(nudge with light-touch help), or "sales" (route to the sales team)
- confidence: a number from 0.0 to 1.0 - the probability that your tier call \
is correct. Calibrate honestly: 0.9 means you expect to be right 90% of the time.
- reason: one short sentence.

Weight current usage signals and buying intent at least as much as employer \
size. A big employer does not make a personal project an enterprise lead.

Lead:
{lead_block}

Respond with ONLY a JSON object on one line, no other text:
{{"tier": "...", "route": "...", "confidence": 0.0, "reason": "..."}}"""


class ParseError(ValueError):
    """Raised when a model response cannot be parsed into a valid call."""


@dataclass
class QualificationCall:
    tier: str
    route: str
    confidence: float
    reason: str


def lead_block(lead: Dict[str, Any]) -> str:
    """Render the observable part of a lead. Truth labels are never shown."""
    company = lead["company"]
    contact = lead["contact"]
    signals = lead["signals"]
    lines = [
        f"company: {company['name']} ({company['domain']})",
        f"industry: {company['industry']}",
        f"employees: {company['employees']}",
        f"contact_role: {contact['role']}",
        f"plan: {signals['plan']}",
        f"seats_active: {signals['seats_active']}",
        f"devices: {signals['devices']}",
        f"days_since_signup: {signals['days_since_signup']}",
        f"features_used: {', '.join(signals['features_used']) or 'none'}",
        f"invited_teammates: {signals['invited_teammates']}",
        f"support_tickets: {signals['support_tickets']}",
        f"asked_about_pricing: {signals['asked_about_pricing']}",
        f"domain_claimed: {signals['domain_claimed']}",
    ]
    return "\n".join(lines)


def build_prompt(lead: Dict[str, Any]) -> str:
    return PROMPT_TEMPLATE.format(lead_block=lead_block(lead))


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_response(text: str) -> QualificationCall:
    """Extract and validate a QualificationCall from raw model output.

    Raises ParseError on anything unusable; the harness records parse failures
    as first-class results rather than discarding them.
    """
    match = _JSON_RE.search(text or "")
    if not match:
        raise ParseError(f"no JSON object in response: {text[:200]!r}")
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ParseError(f"invalid JSON: {exc}") from exc
    tier = str(obj.get("tier", "")).strip().lower()
    route = str(obj.get("route", "")).strip().lower()
    if tier not in TIERS:
        raise ParseError(f"bad tier: {tier!r}")
    if route not in ROUTES:
        raise ParseError(f"bad route: {route!r}")
    try:
        confidence = float(obj.get("confidence"))
    except (TypeError, ValueError) as exc:
        raise ParseError(f"bad confidence: {obj.get('confidence')!r}") from exc
    confidence = min(1.0, max(0.0, confidence))
    reason = str(obj.get("reason", ""))[:300]
    return QualificationCall(tier=tier, route=route,
                             confidence=confidence, reason=reason)
