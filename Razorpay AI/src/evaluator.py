"""
Honest Evaluator Module.
Compares reconciliation decisions against the hidden Ground Truth dataset.
Computes:
- Overall & per-stage match rate
- Strict Financial Precision & Recall (False matches matter more than misses)
- Error Type Confusion Breakdown across all injected error classes
- Throughput and Cost Analysis
"""

from typing import Dict, List, Any
from src.models import GroundTruthRecord, ReconciliationMatch


def evaluate_reconciliation(
    matches: List[ReconciliationMatch],
    ground_truth: List[GroundTruthRecord],
    pipeline_summary: Dict[str, Any],
    llm_telemetry: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Evaluates matches against ground truth groups.
    """
    gt_by_id = {gt.match_group_id: gt for gt in ground_truth}

    # Map record IDs to match objects
    bank_to_match: Dict[str, ReconciliationMatch] = {}
    gw_to_match: Dict[str, ReconciliationMatch] = {}
    inv_to_match: Dict[str, ReconciliationMatch] = {}

    for m in matches:
        for b in m.bank_txn_ids:
            bank_to_match[b] = m
        for g in m.gateway_settlement_ids:
            gw_to_match[g] = m
        for i in m.invoice_ids:
            inv_to_match[i] = m

    # Metrics counters
    tp = 0  # Expected AUTO_MATCH and correctly matched without false links
    fp = 0  # Falsely linked records that belong to different groups
    fn = 0  # Expected match but left unresolved
    tn = 0  # Expected UNRESOLVED (truly unmatched) and correctly unresolved
    correct_reviews = 0  # Expected NEEDS_REVIEW (duplicates, anomalies) correctly flagged

    # Confusion breakdown by error class
    confusion_by_type: Dict[str, Dict[str, int]] = {}

    for gt in ground_truth:
        etype = gt.injected_error_type
        if etype not in confusion_by_type:
            confusion_by_type[etype] = {
                "total": 0,
                "auto_matched": 0,
                "needs_review": 0,
                "unresolved": 0,
                "correct_decision": 0,
                "false_links": 0
            }

        conf_entry = confusion_by_type[etype]
        conf_entry["total"] += 1

        # Determine how our pipeline classified this ground truth group
        associated_matches = set()
        for b in gt.bank_txn_ids:
            if b in bank_to_match:
                associated_matches.add(bank_to_match[b].match_id)
        for g in gt.gateway_settlement_ids:
            if g in gw_to_match:
                associated_matches.add(gw_to_match[g].match_id)
        for i in gt.invoice_ids:
            if i in inv_to_match:
                associated_matches.add(inv_to_match[i].match_id)

        # Check for cross-contamination (false link)
        has_false_link = False
        matched_objs = [m for m in matches if m.match_id in associated_matches]

        for m in matched_objs:
            # Check if match contains bank/gw/inv not in this GT group
            for b in m.bank_txn_ids:
                if b not in gt.bank_txn_ids:
                    has_false_link = True
            for g in m.gateway_settlement_ids:
                if g not in gt.gateway_settlement_ids:
                    has_false_link = True
            for i in m.invoice_ids:
                if i not in gt.invoice_ids:
                    has_false_link = True

        # Primary decision assigned to this group
        if not matched_objs:
            pred_status = "UNRESOLVED"
        else:
            # If any matched object is AUTO_MATCHED, group is treated as auto-matched
            statuses = [m.status for m in matched_objs]
            if "AUTO_MATCHED" in statuses:
                pred_status = "AUTO_MATCHED"
            elif "NEEDS_REVIEW" in statuses:
                pred_status = "NEEDS_REVIEW"
            else:
                pred_status = "UNRESOLVED"

        if pred_status == "AUTO_MATCHED":
            conf_entry["auto_matched"] += 1
        elif pred_status == "NEEDS_REVIEW":
            conf_entry["needs_review"] += 1
        else:
            conf_entry["unresolved"] += 1

        if has_false_link:
            conf_entry["false_links"] += 1
            fp += 1
        else:
            if gt.expected_decision == "AUTO_MATCH":
                if pred_status == "AUTO_MATCHED":
                    tp += 1
                    conf_entry["correct_decision"] += 1
                elif pred_status == "NEEDS_REVIEW":
                    # Partially conservative
                    conf_entry["correct_decision"] += 1
                else:
                    fn += 1

            elif gt.expected_decision == "NEEDS_REVIEW":
                if pred_status == "NEEDS_REVIEW":
                    correct_reviews += 1
                    conf_entry["correct_decision"] += 1
                elif pred_status == "AUTO_MATCHED":
                    # Forcing a match on an anomaly is penalized as a false positive
                    fp += 1
                else:
                    conf_entry["correct_decision"] += 1

            elif gt.expected_decision == "UNRESOLVED":
                if pred_status == "UNRESOLVED":
                    tn += 1
                    conf_entry["correct_decision"] += 1
                else:
                    # Falsely forced an unmatched orphan into a match!
                    fp += 1
                    conf_entry["false_links"] += 1

    # Precision & Recall calculations
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    total_gt = len(ground_truth)
    accuracy = (tp + tn + correct_reviews) / total_gt if total_gt > 0 else 0.0

    # Match rates
    auto_count = pipeline_summary.get("auto_matched_count", 0)
    det_count = pipeline_summary.get("deterministic_count", 0)
    rule_count = pipeline_summary.get("rule_based_count", 0)
    llm_count = pipeline_summary.get("llm_count", 0)
    total_matches = pipeline_summary.get("total_matches_formed", 1)

    stage_breakdown = {
        "deterministic": {
            "count": det_count,
            "share_percent": round((det_count / max(1, total_matches)) * 100, 1)
        },
        "rule_based": {
            "count": rule_count,
            "share_percent": round((rule_count / max(1, total_matches)) * 100, 1)
        },
        "llm": {
            "count": llm_count,
            "share_percent": round((llm_count / max(1, total_matches)) * 100, 1)
        }
    }

    # Accuracy percentage per error class
    confusion_report = {}
    for etype, data in confusion_by_type.items():
        rate = round((data["correct_decision"] / data["total"]) * 100, 1) if data["total"] > 0 else 0.0
        confusion_report[etype] = {
            **data,
            "accuracy_percent": rate
        }

    return {
        "reconciliation_metrics": {
            "total_ground_truth_records": total_gt,
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
            "true_negatives": tn,
            "correct_reviews_flagged": correct_reviews,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1_score": round(f1, 4),
            "overall_accuracy_percent": round(accuracy * 100, 1),
            "auto_match_rate_percent": round((auto_count / total_gt) * 100, 1),
        },
        "stage_breakdown": stage_breakdown,
        "confusion_by_injected_error_type": confusion_report,
        "performance_and_cost": {
            "throughput_records_sec": pipeline_summary.get("throughput_records_per_sec", 0.0),
            "elapsed_seconds": pipeline_summary.get("elapsed_seconds", 0.0),
            "llm_calls_made": llm_telemetry.get("llm_calls_count", 0),
            "estimated_cost_usd": llm_telemetry.get("estimated_cost_usd", 0.0),
            "estimated_cost_inr": llm_telemetry.get("estimated_cost_inr", 0.0),
            "llm_provider": llm_telemetry.get("llm_provider", "Unknown")
        }
    }
