import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.generate_leads import generate  # noqa: E402


class TestLeadGen(unittest.TestCase):
    def test_deterministic(self):
        a = generate(n=40, seed=1)
        b = generate(n=40, seed=1)
        self.assertEqual([l.truth for l in a], [l.truth for l in b])
        self.assertEqual([l.signals for l in a], [l.signals for l in b])

    def test_schema_and_labels(self):
        leads = generate(n=60, seed=2)
        self.assertEqual(len(leads), 60)
        ids = set()
        for lead in leads:
            ids.add(lead.id)
            self.assertIn(lead.truth["tier"],
                          ("personal_dev", "team", "enterprise"))
            self.assertIn(lead.truth["route"],
                          ("self_serve", "sales_assist", "sales"))
            self.assertTrue(lead.truth["reason"])
            self.assertGreaterEqual(lead.company["employees"], 1)
        self.assertEqual(len(ids), 60)

    def test_tricky_subset_exists_and_is_labeled(self):
        leads = generate(n=120, seed=3)
        tricky = [l for l in leads if l.tricky]
        self.assertGreater(len(tricky), 10)
        # The enterprise-personal-use trap must exist and be labeled dev.
        traps = [l for l in tricky
                 if l.company["employees"] >= 1000
                 and l.truth["tier"] == "personal_dev"]
        self.assertGreater(len(traps), 0)


if __name__ == "__main__":
    unittest.main()
