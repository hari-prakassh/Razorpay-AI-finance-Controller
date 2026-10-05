"""
Unit tests for Flask Web Application & API endpoints.
"""

import json
import unittest
from src.web_app import app, init_app_state


class TestWebApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_app_state()
        cls.client = app.test_client()

    def test_index_page(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"AI Finance Controller", resp.data)
        self.assertIn(b"Executive Reconciliation Dashboard", resp.data)

    def test_status_endpoint(self):
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data.decode("utf-8"))
        self.assertIn("metrics", data)
        self.assertIn("summary", data)
        self.assertIn("stage_breakdown", data)
        self.assertEqual(data["metrics"]["precision"], 1.0)

    def test_matches_endpoint(self):
        resp = self.client.get("/api/matches?status=AUTO_MATCHED")
        self.assertEqual(resp.status_code, 200)
        matches = json.loads(resp.data.decode("utf-8"))
        self.assertGreater(len(matches), 50)
        for m in matches:
            self.assertEqual(m["status"], "AUTO_MATCHED")

    def test_exceptions_endpoint(self):
        resp = self.client.get("/api/exceptions")
        self.assertEqual(resp.status_code, 200)
        exceptions = json.loads(resp.data.decode("utf-8"))
        self.assertGreaterEqual(len(exceptions), 5)
        for exc in exceptions:
            self.assertIn("suggested_human_action", exc)
            self.assertIn("root_cause_explanation", exc)

    def test_in_app_chat_copilot(self):
        resp = self.client.post(
            "/api/chat",
            data=json.dumps({"message": "Why did you flag EXC-001?"}),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data.decode("utf-8"))
        self.assertIn("response", data)
        self.assertIn("Forensic Audit for Exception", data["response"])

    def test_add_custom_transaction(self):
        payload = {
            "source_type": "bank",
            "bank_txn_id": "BNK-TEST-UNIT",
            "txn_date": "2026-09-30",
            "narration": "UPI/CR/429900112233/TEST/Razorpay",
            "deposit_inr": 5000.0,
            "utr_number": "429900112233",
            "bank_name": "ICICI Bank"
        }
        resp = self.client.post(
            "/api/add-transaction",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data.decode("utf-8"))
        self.assertTrue(data["success"])


if __name__ == "__main__":
    unittest.main()
