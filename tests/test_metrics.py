import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import metrics  # noqa: E402


def row(lead_id, true_tier, pred_tier, run_index=0, conf=0.8,
        true_route="self_serve", pred_route="self_serve", tricky=False):
    return {"arm": "treatment", "run_index": run_index, "lead_id": lead_id,
            "tricky": tricky, "true_tier": true_tier, "pred_tier": pred_tier,
            "true_route": true_route, "pred_route": pred_route,
            "confidence": conf, "parse_ok": True, "error": None}


class TestMetrics(unittest.TestCase):
    def test_accuracy_with_denominators(self):
        rows = [row("a", "team", "team"), row("b", "team", "enterprise"),
                row("c", "enterprise", "enterprise"),
                row("d", "personal_dev", "personal_dev")]
        acc = metrics.accuracy(rows, "tier")
        self.assertEqual(acc["n"], 4)
        self.assertEqual(acc["correct"], 3)
        self.assertAlmostEqual(acc["accuracy"], 0.75)
        self.assertEqual(acc["by_segment"]["team"]["n"], 2)
        self.assertEqual(acc["by_segment"]["team"]["correct"], 1)

    def test_confusion_pairs(self):
        rows = [row("a", "enterprise", "personal_dev"),
                row("b", "enterprise", "personal_dev"),
                row("c", "enterprise", "enterprise")]
        conf = metrics.confusion(rows, "tier")
        self.assertEqual(conf[0]["true"], "enterprise")
        self.assertEqual(conf[0]["pred"], "personal_dev")
        self.assertEqual(conf[0]["n"], 2)

    def test_brier_hand_computed(self):
        rows = [row("a", "team", "team", conf=1.0),
                row("b", "team", "enterprise", conf=1.0)]
        cal = metrics.calibration(rows)
        # (1-1)^2 + (1-0)^2 over 2 rows
        self.assertAlmostEqual(cal["brier"], 0.5)
        self.assertEqual(cal["n"], 2)

    def test_flip_rate(self):
        rows = []
        for run in range(4):
            rows.append(row("a", "team", "team", run_index=run))
        rows.append(row("b", "team", "team", run_index=0))
        rows.append(row("b", "team", "enterprise", run_index=1))
        flip = metrics.flip_rate(rows)
        by_lead = {f["lead_id"]: f["flip"] for f in
                   [dict(lead_id="a", flip=0.0), dict(lead_id="b", flip=0.5)]}
        self.assertAlmostEqual(by_lead["a"], 0.0)
        self.assertAlmostEqual(by_lead["b"], 0.5)

    def test_parse_failures_counted(self):
        rows = [row("a", "team", "team"),
                {"arm": "treatment", "run_index": 0, "lead_id": "b",
                 "tricky": False, "true_tier": "team", "pred_tier": None,
                 "true_route": "sales_assist", "pred_route": None,
                 "confidence": None, "parse_ok": False, "error": "no JSON"}]
        pf = metrics.parse_failures(rows)
        self.assertEqual(pf["failures"], 1)
        self.assertEqual(pf["n"], 2)


if __name__ == "__main__":
    unittest.main()
