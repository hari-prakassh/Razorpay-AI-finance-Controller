"""Tests for synthetic data generation."""

import os
import csv
import unittest
from src.data_generator import generate_synthetic_dataset


class TestDataGenerator(unittest.TestCase):
    def setUp(self):
        self.output_dir = "data"
        self.stats = generate_synthetic_dataset(output_dir=self.output_dir, seed=42)

    def test_file_existence(self):
        self.assertTrue(os.path.exists("data/bank_statement.csv"))
        self.assertTrue(os.path.exists("data/gateway_settlements.csv"))
        self.assertTrue(os.path.exists("data/internal_ledger.csv"))
        self.assertTrue(os.path.exists("data/ground_truth.csv"))

    def test_record_counts(self):
        # 60-100 records requirement
        self.assertGreaterEqual(self.stats["bank_records_count"], 60)
        self.assertLessEqual(self.stats["bank_records_count"], 100)
        self.assertGreaterEqual(self.stats["gateway_records_count"], 60)
        self.assertLessEqual(self.stats["gateway_records_count"], 100)
        self.assertGreaterEqual(self.stats["ledger_records_count"], 60)
        self.assertLessEqual(self.stats["ledger_records_count"], 100)

    def test_ground_truth_distributions(self):
        with open("data/ground_truth.csv", "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
        error_types = [r["injected_error_type"] for r in reader]

        clean_exact = error_types.count("CLEAN_EXACT")
        fuzzy = error_types.count("FUZZY_REFERENCE")
        fee_tds = error_types.count("FEE_TDS_AMOUNT_MISMATCH")
        date_drift = error_types.count("DATE_DRIFT")
        duplicates = error_types.count("DUPLICATE")
        split_merged = error_types.count("SPLIT_MERGED")
        unmatched = error_types.count("TRULY_UNMATCHED")

        total = len(reader)
        self.assertEqual(total, 80)
        self.assertAlmostEqual(clean_exact / total, 0.60, delta=0.03)
        self.assertAlmostEqual(fuzzy / total, 0.15, delta=0.03)
        self.assertAlmostEqual(fee_tds / total, 0.0875, delta=0.03)
        self.assertAlmostEqual(date_drift / total, 0.05, delta=0.02)
        self.assertAlmostEqual(duplicates / total, 0.0375, delta=0.02)
        self.assertAlmostEqual(split_merged / total, 0.0375, delta=0.02)
        self.assertAlmostEqual(unmatched / total, 0.0375, delta=0.02)


if __name__ == "__main__":
    unittest.main()
