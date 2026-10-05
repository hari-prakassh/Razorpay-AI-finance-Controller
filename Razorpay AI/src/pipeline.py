"""
AI Finance Controller Reconciliation Pipeline.
Orchestrates:
1. Loader
2. Pass A: Deterministic Exact Pass
3. Pass B: Rule-Based Domain Pass
4. Pass C: LLM Residual Pass (Claude API / Fallback Reasoner)
5. Pass D: Confidence Gating
"""

import time
from typing import Dict, List, Tuple, Any, Optional
from src.models import (
    BankTransaction, GatewaySettlement, InternalInvoice,
    GroundTruthRecord, ReconciliationMatch
)
from src.engine.loader import load_dataset
from src.engine.deterministic import run_deterministic_pass
from src.engine.rule_based import run_rule_based_pass
from src.engine.llm_matcher import LLMMatcher
from src.engine.gating import apply_confidence_gating


class ReconciliationPipeline:
    def __init__(self, data_dir: str = "data", api_key: Optional[str] = None):
        self.data_dir = data_dir
        self.llm_matcher = LLMMatcher(api_key=api_key)

    def run(self) -> Dict[str, Any]:
        """
        Executes end-to-end multi-source reconciliation.
        Returns all matches, categorized lists, performance stats, and audit logs.
        """
        start_time = time.time()

        # 1. Load Data
        bank_records, gateway_records, ledger_records, ground_truth = load_dataset(self.data_dir)
        total_input_records = len(bank_records) + len(gateway_records) + len(ledger_records)

        # 2. Pass A: Deterministic Pass
        det_matches, rem_bank_a, rem_gw_a, rem_ledger_a = run_deterministic_pass(
            bank_records, gateway_records, ledger_records
        )

        # 3. Pass B: Rule-Based Pass
        rule_matches, rem_bank_b, rem_gw_b, rem_ledger_b = run_rule_based_pass(
            rem_bank_a, rem_gw_a, rem_ledger_a
        )

        # 4. Pass C: LLM Pass on Leftovers
        all_prior_matches = det_matches + rule_matches
        llm_matches = self.llm_matcher.reconcile_leftovers(
            rem_bank_b, rem_gw_b, rem_ledger_b, all_prior_matches
        )

        # Combine all matches
        all_matches = det_matches + rule_matches + llm_matches

        # 5. Pass D: Confidence Gating
        auto_matched, needs_review, unresolved = apply_confidence_gating(all_matches)

        elapsed_seconds = max(0.001, time.time() - start_time)
        throughput_records_sec = round(total_input_records / elapsed_seconds, 1)

        telemetry = self.llm_matcher.get_telemetry()

        return {
            "summary": {
                "total_input_records": total_input_records,
                "bank_records_count": len(bank_records),
                "gateway_records_count": len(gateway_records),
                "ledger_records_count": len(ledger_records),
                "ground_truth_count": len(ground_truth),
                "total_matches_formed": len(all_matches),
                "auto_matched_count": len(auto_matched),
                "needs_review_count": len(needs_review),
                "unresolved_count": len(unresolved),
                "deterministic_count": len(det_matches),
                "rule_based_count": len(rule_matches),
                "llm_count": len(llm_matches),
                "elapsed_seconds": round(elapsed_seconds, 3),
                "throughput_records_per_sec": throughput_records_sec,
            },
            "llm_telemetry": telemetry,
            "all_matches": all_matches,
            "auto_matched": auto_matched,
            "needs_review": needs_review,
            "unresolved": unresolved,
            "ground_truth": ground_truth
        }
