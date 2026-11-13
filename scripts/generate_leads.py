"""Synthetic lead generator for a PLG free-to-paid motion.

Generates plausible but fully synthetic leads for a generic PLG SaaS product
(a devtools/networking-style tool with a free plan, team tier, and enterprise
tier). Every lead carries ground-truth labels (tier + route) that are hidden
from the pipeline under test, plus a human-readable reason for the label.

A designed subset of leads is "tricky": surface signals conflict with the
truth in ways real GTM pipelines get wrong (e.g. an enterprise employee using
the product personally, or an enterprise with tiny current usage but active
procurement). The reason field documents why each tricky label is what it is.

Everything is deterministic given the seed. No real company data is used.
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass, field, asdict
from typing import List

TIERS = ["personal_dev", "team", "enterprise"]
ROUTES = ["self_serve", "sales_assist", "sales"]

FEATURES_BY_TIER = {
    "personal_dev": ["cli_usage", "mobile_app", "personal_devices", "api_tokens"],
    "team": ["team_invites", "shared_workspaces", "api_tokens", "integrations",
             "role_based_access", "audit_logs"],
    "enterprise": ["sso_saml", "scim_provisioning", "audit_logs", "integrations",
                   "role_based_access", "custom_retention", "dlp_controls"],
}

INDUSTRIES = ["software", "fintech", "healthtech", "ecommerce", "gaming",
              "consulting", "manufacturing", "media", "edtech", "logistics"]

FIRST = ["Ava", "Liam", "Maya", "Noah", "Priya", "Owen", "Sofia", "Ethan",
         "Nina", "Lucas", "Iris", "Felix", "Tara", "Hugo", "Lena", "Omar"]
LAST = ["Hayes", "Nguyen", "Patel", "Garcia", "Kim", "Novak", "Silva",
        "Weber", "Okafor", "Larsen", "Mehta", "Brooks", "Ito", "Fischer"]

COMPANY_PARTS_A = ["North", "Blue", "Red", "Silver", "Peak", "Cloud", "Bright",
                   "Swift", "Granite", "Harbor", "Cedar", "Quantum", "Vertex"]
COMPANY_PARTS_B = ["labs", "systems", "works", "stack", "ware", "logic",
                   "forge", "bridge", "nest", "loop", "byte", "grid"]

ROLES = {
    "personal_dev": ["software engineer", "student", "indie hacker", "hobbyist"],
    "team": ["engineering manager", "team lead", "it admin", "staff engineer"],
    "enterprise": ["cio", "vp it", "head of platform", "procurement manager",
                   "security architect", "it director"],
}


@dataclass
class Lead:
    id: str
    tricky: bool
    company: dict
    contact: dict
    signals: dict
    truth: dict = field(default_factory=dict)


def _company_name(rng: random.Random) -> str:
    return rng.choice(COMPANY_PARTS_A) + rng.choice(COMPANY_PARTS_B)


def _base_signals(rng: random.Random, tier: str) -> dict:
    """Usage signals typical of the tier (before tricky perturbation)."""
    if tier == "personal_dev":
        return {
            "plan": "free",
            "seats_active": 1,
            "devices": rng.randint(1, 4),
            "days_since_signup": rng.randint(3, 400),
            "features_used": rng.sample(FEATURES_BY_TIER["personal_dev"],
                                        k=rng.randint(1, 3)),
            "invited_teammates": 0,
            "support_tickets": rng.choice([0, 0, 0, 1]),
            "asked_about_pricing": False,
            "domain_claimed": False,
        }
    if tier == "team":
        return {
            "plan": rng.choice(["free", "free", "team_trial"]),
            "seats_active": rng.randint(3, 25),
            "devices": rng.randint(8, 120),
            "days_since_signup": rng.randint(10, 500),
            "features_used": rng.sample(FEATURES_BY_TIER["team"],
                                        k=rng.randint(2, 4)),
            "invited_teammates": rng.randint(1, 12),
            "support_tickets": rng.randint(0, 4),
            "asked_about_pricing": rng.random() < 0.45,
            "domain_claimed": rng.random() < 0.3,
        }
    return {
        "plan": rng.choice(["free", "team_trial", "enterprise_trial"]),
        "seats_active": rng.randint(20, 400),
        "devices": rng.randint(80, 3000),
        "days_since_signup": rng.randint(15, 700),
        "features_used": rng.sample(FEATURES_BY_TIER["enterprise"],
                                    k=rng.randint(2, 5)),
        "invited_teammates": rng.randint(5, 80),
        "support_tickets": rng.randint(0, 8),
        "asked_about_pricing": rng.random() < 0.7,
        "domain_claimed": rng.random() < 0.75,
    }


def _company_for(rng: random.Random, tier: str) -> dict:
    name = _company_name(rng)
    if tier == "personal_dev":
        employees = rng.choice([1, 2, 5, 10, 25, 60])
    elif tier == "team":
        employees = rng.randint(15, 900)
    else:
        employees = rng.randint(1000, 60000)
    return {
        "name": name,
        "domain": f"{name.lower()}.example",
        "industry": rng.choice(INDUSTRIES),
        "employees": employees,
    }


def _contact_for(rng: random.Random, tier: str) -> dict:
    return {
        "name": f"{rng.choice(FIRST)} {rng.choice(LAST)}",
        "role": rng.choice(ROLES[tier]),
    }


def _truth(tier: str, route: str, reason: str) -> dict:
    return {"tier": tier, "route": route, "reason": reason}


TRICKY_KINDS = [
    "enterprise_company_personal_use",
    "enterprise_low_usage",
    "team_high_usage",
    "team_buying_intent_small",
]


def _make_clean(rng: random.Random, idx: int, tier: str) -> Lead:
    lead = Lead(id=f"L{idx:04d}", tricky=False,
                company=_company_for(rng, tier),
                contact=_contact_for(rng, tier),
                signals=_base_signals(rng, tier))
    if tier == "personal_dev":
        lead.truth = _truth(tier, "self_serve",
                            "Individual usage, small or no team behind it.")
    elif tier == "team":
        route = ("sales_assist" if (lead.signals["asked_about_pricing"]
                                    or lead.company["employees"] > 100)
                 else "self_serve")
        lead.truth = _truth(tier, route,
                            "Team-scale usage at a mid-size company.")
    else:
        lead.truth = _truth(tier, "sales",
                            "Enterprise-scale company with enterprise features in use.")
    return lead


def _make_tricky(rng: random.Random, idx: int, kind: str) -> Lead:
    if kind == "enterprise_company_personal_use":
        # Big employer, but the usage is one engineer's homelab.
        lead = Lead(id=f"L{idx:04d}", tricky=True,
                    company=_company_for(rng, "enterprise"),
                    contact=_contact_for(rng, "personal_dev"),
                    signals=_base_signals(rng, "personal_dev"))
        lead.contact["role"] = "software engineer"
        lead.truth = _truth("personal_dev", "self_serve",
                            "Employer is enterprise-scale, but every usage signal "
                            "is a single engineer's personal setup. Employer size "
                            "is not the lead.")
    elif kind == "enterprise_low_usage":
        # Enterprise in early evaluation: tiny usage, strong intent signals.
        lead = Lead(id=f"L{idx:04d}", tricky=True,
                    company=_company_for(rng, "enterprise"),
                    contact=_contact_for(rng, "enterprise"),
                    signals=_base_signals(rng, "enterprise"))
        lead.signals["seats_active"] = rng.randint(2, 6)
        lead.signals["devices"] = rng.randint(3, 15)
        lead.signals["invited_teammates"] = rng.randint(0, 3)
        lead.signals["asked_about_pricing"] = True
        lead.signals["domain_claimed"] = True
        lead.truth = _truth("enterprise", "sales",
                            "Usage numbers are tiny, but this is an enterprise "
                            "running a structured evaluation: pricing questions, "
                            "claimed domain, enterprise features touched.")
    elif kind == "team_high_usage":
        # Mid-size company with usage volume that looks enterprise.
        lead = Lead(id=f"L{idx:04d}", tricky=True,
                    company=_company_for(rng, "team"),
                    contact=_contact_for(rng, "team"),
                    signals=_base_signals(rng, "team"))
        lead.signals["devices"] = rng.randint(400, 1500)
        lead.signals["seats_active"] = rng.randint(30, 90)
        lead.truth = _truth("team", "sales_assist",
                            "Usage volume looks enterprise, but the company is "
                            "mid-size with no enterprise procurement signals. "
                            "Heavy teams need assistance, not an enterprise cycle.")
    else:  # team_buying_intent_small
        # Small team explicitly asking about paid plans: easy to mark low-fit.
        lead = Lead(id=f"L{idx:04d}", tricky=True,
                    company=_company_for(rng, "team"),
                    contact=_contact_for(rng, "team"),
                    signals=_base_signals(rng, "team"))
        lead.company["employees"] = rng.randint(8, 30)
        lead.signals["seats_active"] = rng.randint(2, 8)
        lead.signals["devices"] = rng.randint(4, 25)
        lead.signals["asked_about_pricing"] = True
        lead.truth = _truth("team", "sales_assist",
                            "Small in absolute numbers, but asking about pricing "
                            "with real team features in use. Easy to under-score "
                            "as low fit.")
    return lead


def generate(n: int = 120, seed: int = 20261114, tricky_fraction: float = 0.25
             ) -> List[Lead]:
    rng = random.Random(seed)
    leads: List[Lead] = []
    tier_weights = [("personal_dev", 0.40), ("team", 0.35), ("enterprise", 0.25)]
    tiers = [t for t, _ in tier_weights]
    weights = [w for _, w in tier_weights]
    for i in range(1, n + 1):
        if rng.random() < tricky_fraction:
            kind = rng.choice(TRICKY_KINDS)
            leads.append(_make_tricky(rng, i, kind))
        else:
            tier = rng.choices(tiers, weights=weights, k=1)[0]
            leads.append(_make_clean(rng, i, tier))
    rng.shuffle(leads)
    for new_i, lead in enumerate(leads, start=1):
        lead.id = f"L{new_i:04d}"
    return leads


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate synthetic PLG leads.")
    ap.add_argument("--n", type=int, default=120)
    ap.add_argument("--seed", type=int, default=20261114)
    ap.add_argument("--out", default="data/leads.jsonl")
    args = ap.parse_args()
    leads = generate(n=args.n, seed=args.seed)
    with open(args.out, "w", encoding="utf-8") as fh:
        for lead in leads:
            fh.write(json.dumps(asdict(lead), sort_keys=True) + "\n")
    tiers = {}
    tricky = 0
    for lead in leads:
        tiers[lead.truth["tier"]] = tiers.get(lead.truth["tier"], 0) + 1
        tricky += int(lead.tricky)
    print(f"wrote {len(leads)} leads to {args.out}")
    print(f"tiers: {tiers}; tricky: {tricky}")


if __name__ == "__main__":
    main()
