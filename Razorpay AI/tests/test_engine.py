"""
Unit tests for Reconciliation Engine & Pipeline.
"""

import unittest
from src.engine.loader import load_dataset
from src.engine.deterministic import run_deterministic_pass
from src.engine.rule_based import run_rule_based_pass
from src.engine.gating import apply_confidence_gating
from src.pipeline import ReconciliationPipeline
from src.evaluator import evaluate_reconciliation
from src.models import ReconciliationMatch


class TestReconciliationEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bank, cls.gateway, cls.ledger, cls.gt = load_dataset("data")

    def test_deterministic_pass(self):
        matches, rem_b, rem_g, rem_l = run_deterministic_pass(self.bank, self.gateway, self.ledger)
        self.assertGreater(len(matches), 50)
        for m in matches:
            self.assertEqual(m.confidence, 1.0)
            self.assertEqual(m.stage, "DETERMINISTIC")
            self.assertEqual(m.status, "AUTO_MATCHED")

    def test_rule_based_pass(self):
        det_matches, rem_b, rem_g, rem_l = run_deterministic_pass(self.bank, self.gateway, self.ledger)
        rule_matches, r_b, r_g, r_l = run_rule_based_pass(rem_b, rem_g, rem_l)
        self.assertGreater(len(rule_matches), 10)

        # Check split batch settlement was detected
        split_matches = [m for m in rule_matches if "SPLIT" in m.match_id]
        self.assertGreaterEqual(len(split_matches), 1)

        # Check duplicate anomalies were caught
        dup_matches = [m for m in rule_matches if "DUP" in m.match_id]
        self.assertGreaterEqual(len(dup_matches), 2)
        for d in dup_matches:
            self.assertEqual(d.status, "NEEDS_REVIEW")

    def test_confidence_gating(self):
        m1 = ReconciliationMatch("M1", "AUTO_MATCHED", "DETERMINISTIC", 0.95)
        m2 = ReconciliationMatch("M2", "NEEDS_REVIEW", "RULE_BASED", 0.70)
        m3 = ReconciliationMatch("M3", "UNRESOLVED", "LLM", 0.20)

        auto, review, unres = apply_confidence_gating([m1, m2, m3])
        self.assertEqual(len(auto), 1)
        self.assertEqual(len(review), 1)
        self.assertEqual(len(unres), 1)
        self.assertEqual(auto[0].match_id, "M1")
        self.assertEqual(review[0].match_id, "M2")
        self.assertEqual(unres[0].match_id, "M3")

    def test_end_to_end_accuracy(self):
        pipeline = ReconciliationPipeline(data_dir="data")
        results = pipeline.run()
        eval_metrics = evaluate_reconciliation(
            results["all_matches"],
            results["ground_truth"],
            results["summary"],
            results["llm_telemetry"]
        )

        metrics = eval_metrics["reconciliation_metrics"]
        # Zero false positives
        self.assertEqual(metrics["false_positives"], 0)
        self.assertEqual(metrics["precision"], 1.0)
        # High recall & match rate
        self.assertGreaterEqual(metrics["auto_match_rate_percent"], 90.0)
        self.assertEqual(metrics["overall_accuracy_percent"], 100.0)


if __name__ == "__main__":
    unittest.main()
