import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import pipeline  # noqa: E402


class TestParse(unittest.TestCase):
    def test_clean_json(self):
        call = pipeline.parse_response(
            '{"tier": "team", "route": "sales_assist", '
            '"confidence": 0.7, "reason": "team signals"}')
        self.assertEqual(call.tier, "team")
        self.assertEqual(call.route, "sales_assist")
        self.assertAlmostEqual(call.confidence, 0.7)

    def test_json_in_prose(self):
        call = pipeline.parse_response(
            'Sure! {"tier": "enterprise", "route": "sales", '
            '"confidence": 1.4, "reason": "big"} hope that helps')
        self.assertEqual(call.tier, "enterprise")
        self.assertEqual(call.confidence, 1.0)  # clamped

    def test_bad_tier_rejected(self):
        with self.assertRaises(pipeline.ParseError):
            pipeline.parse_response(
                '{"tier": "whale", "route": "sales", "confidence": 0.9}')

    def test_no_json_rejected(self):
        with self.assertRaises(pipeline.ParseError):
            pipeline.parse_response("I think this is a team lead.")

    def test_prompt_hides_truth(self):
        lead = {
            "id": "L1", "tricky": False,
            "company": {"name": "X", "domain": "x.example",
                        "industry": "software", "employees": 50},
            "contact": {"name": "A B", "role": "team lead"},
            "signals": {"plan": "free", "seats_active": 4, "devices": 9,
                        "days_since_signup": 30, "features_used": ["sso_saml"],
                        "invited_teammates": 2, "support_tickets": 0,
                        "asked_about_pricing": True, "domain_claimed": False},
            "truth": {"tier": "team", "route": "sales_assist",
                      "reason": "secret"},
        }
        prompt = pipeline.build_prompt(lead)
        self.assertIn("employees: 50", prompt)
        self.assertNotIn("secret", prompt)
        self.assertNotIn('"truth"', prompt)


if __name__ == "__main__":
    unittest.main()
