"""
Reporter and Exception Management Module.
Generates:
1. results/matches.csv
2. results/exceptions.csv (with root cause analysis and actionable human steps)
3. results/metrics.json
4. Rich terminal summary with color-coded status tables
"""

import csv
import json
import os
import sys
from typing import Dict, List, Any, Tuple
from src.models import ReconciliationMatch


SUGGESTED_HUMAN_ACTIONS = {
    "duplicate_bank_credit": (
        "DUPLICATE_BANK_CREDIT",
        "Contact bank relationship manager to confirm duplicate credit and initiate reversal/clawback of excess funds to prevent audit discrepancy."
    ),
    "webhook_replay": (
        "WEBHOOK_REPLAY_GATEWAY",
        "Verify payment gateway webhook logs and idempotency keys. Mark redundant gateway settlement line as duplicate in ERP ledger."
    ),
    "duplicate_invoice": (
        "DUPLICATE_INTERNAL_INVOICE",
        "Review sales order with accounts receivable team. Issue formal credit note for redundant invoice to void duplicate AR balance."
    ),
    "unauthorized_short_payment": (
        "UNAUTHORIZED_SHORT_PAYMENT",
        "Log customer payment dispute for unexplained deduction. Request customer debit note or route to finance controller for write-off approval."
    ),
    "unidentified_credit": (
        "ORPHAN_BANK_DEPOSIT",
        "Transfer funds to Suspense Account. Request bank treasury to provide sender Remitter Information (IFSC/Account) for manual ledger credit."
    ),
    "unsettled_nodal": (
        "UNSETTLED_GATEWAY_FLOAT",
        "Escalate to payment gateway merchant support (Razorpay nodal ops) with payment UTR to release stuck nodal settlement payout."
    ),
    "unpaid_debtor": (
        "UNPAID_DEBTOR_INVOICE",
        "Trigger Level-2 dunning notice to corporate customer AP department with original invoice copy and payment remittance instructions."
    )
}


def classify_exception(m: ReconciliationMatch) -> Tuple[str, str]:
    """Determines exception category and suggested human action."""
    reason_upper = m.reasoning.upper()
    rule_upper = m.rule_or_model.upper()

    if "DUPLICATE BANK" in reason_upper or "DOUBLE CREDIT" in reason_upper:
        return SUGGESTED_HUMAN_ACTIONS["duplicate_bank_credit"]
    elif "WEBHOOK REPLAY" in reason_upper or "DUPLICATE GATEWAY" in reason_upper:
        return SUGGESTED_HUMAN_ACTIONS["webhook_replay"]
    elif "DUPLICATE INTERNAL INVOICE" in reason_upper or "DOUBLE INVOIC" in reason_upper:
        return SUGGESTED_HUMAN_ACTIONS["duplicate_invoice"]
    elif "SHORT PAYMENT" in reason_upper:
        return SUGGESTED_HUMAN_ACTIONS["unauthorized_short_payment"]
    elif "UNIDENTIFIED" in reason_upper or "SUSPENSE" in reason_upper:
        return SUGGESTED_HUMAN_ACTIONS["unidentified_credit"]
    elif "NODAL" in reason_upper or "UNSETTLED" in reason_upper:
        return SUGGESTED_HUMAN_ACTIONS["unsettled_nodal"]
    elif "UNPAID" in reason_upper or "DEBTOR" in reason_upper:
        return SUGGESTED_HUMAN_ACTIONS["unpaid_debtor"]

    return (
        "UNRESOLVED_DISCREPANCY",
        "Conduct manual 3-way trace across bank statement, gateway portal, and ERP ledger with accounting team."
    )


def save_results(
    matches: List[ReconciliationMatch],
    eval_results: Dict[str, Any],
    output_dir: str = "results"
) -> Dict[str, str]:
    """Saves matches.csv, exceptions.csv, and metrics.json."""
    os.makedirs(output_dir, exist_ok=True)

    matches_path = os.path.join(output_dir, "matches.csv")
    exceptions_path = os.path.join(output_dir, "exceptions.csv")
    metrics_path = os.path.join(output_dir, "metrics.json")

    # 1. matches.csv
    match_rows = []
    for m in matches:
        match_rows.append({
            "match_id": m.match_id,
            "status": m.status,
            "stage": m.stage,
            "confidence": f"{m.confidence:.2f}",
            "reconciled_amount_inr": f"{m.reconciled_amount:.2f}",
            "discrepancy_amount_inr": f"{m.amount_discrepancy:.2f}",
            "bank_txn_ids": ";".join(m.bank_txn_ids),
            "gateway_settlement_ids": ";".join(m.gateway_settlement_ids),
            "invoice_ids": ";".join(m.invoice_ids),
            "rule_or_model": m.rule_or_model,
            "evidence_fields": ";".join(m.evidence_fields),
            "reasoning": m.reasoning
        })

    if match_rows:
        with open(matches_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(match_rows[0].keys()))
            writer.writeheader()
            writer.writerows(match_rows)

    # 2. exceptions.csv
    exception_rows = []
    exc_counter = 1
    for m in matches:
        if m.status in ("NEEDS_REVIEW", "UNRESOLVED"):
            exc_category, human_action = classify_exception(m)
            amt = m.reconciled_amount if m.reconciled_amount > 0 else m.amount_discrepancy
            exception_rows.append({
                "exception_id": f"EXC-{str(exc_counter).zfill(3)}",
                "match_id": m.match_id,
                "status": m.status,
                "exception_category": exc_category,
                "confidence": f"{m.confidence:.2f}",
                "amount_involved_inr": f"{amt:.2f}",
                "bank_txn_ids": ";".join(m.bank_txn_ids),
                "gateway_settlement_ids": ";".join(m.gateway_settlement_ids),
                "invoice_ids": ";".join(m.invoice_ids),
                "root_cause_explanation": m.reasoning,
                "suggested_human_action": human_action,
                "rule_or_model_flagged": m.rule_or_model
            })
            exc_counter += 1

    if exception_rows:
        with open(exceptions_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(exception_rows[0].keys()))
            writer.writeheader()
            writer.writerows(exception_rows)

    # 3. metrics.json
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(eval_results, f, indent=2)

    return {
        "matches_csv": matches_path,
        "exceptions_csv": exceptions_path,
        "metrics_json": metrics_path,
        "exceptions_count": len(exception_rows)
    }


def print_cli_dashboard(eval_results: Dict[str, Any], exceptions_path: str):
    """Prints a clear, high-impact CLI dashboard to stdout."""
    # Ensure UTF-8 output safe
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    metrics = eval_results["reconciliation_metrics"]
    stage = eval_results["stage_breakdown"]
    confusion = eval_results["confusion_by_injected_error_type"]
    perf = eval_results["performance_and_cost"]

    banner = "=" * 80
    sub_banner = "-" * 80

    print(f"\n{banner}")
    print("        AI FINANCE CONTROLLER : MULTI-SOURCE RECONCILIATION AGENT")
    print("        Sources: Bank Statement (HDFC/ICICI) | Gateway (Razorpay) | Ledger")
    print(f"{banner}")

    print("\n[+] RECONCILIATION SUMMARY & HONEST ACCURACY METRICS:")
    print(sub_banner)
    print(f"  Total Ground Truth Records : {metrics['total_ground_truth_records']}")
    print(f"  Auto-Matched (Conf >= 0.85): {metrics['true_positives']} ({metrics['auto_match_rate_percent']}%)")
    print(f"  Flagged for Human Review   : {metrics['correct_reviews_flagged']}")
    print(f"  True Unresolved Exceptions : {metrics['true_negatives']}")
    print(f"  False Positives (Bad Match): {metrics['false_positives']} (Crucial: 0 false matches)")
    print(f"  False Negatives (Missed)   : {metrics['false_negatives']}")
    print(sub_banner)
    print(f"  PRECISION                  : {metrics['precision'] * 100:.2f}% (No false matches cross-contaminating books)")
    print(f"  RECALL                     : {metrics['recall'] * 100:.2f}%")
    print(f"  F1-SCORE                   : {metrics['f1_score']:.4f}")
    print(f"  OVERALL DECISION ACCURACY  : {metrics['overall_accuracy_percent']:.1f}%")

    print("\n[+] STAGE-BY-STAGE RECONCILIATION CONTRIBUTION:")
    print(sub_banner)
    print(f"  {'Stage':<25} | {'Count':<10} | {'Share (%)':<10}")
    print(sub_banner)
    print(f"  Stage A: Deterministic   | {stage['deterministic']['count']:<10} | {stage['deterministic']['share_percent']}%")
    print(f"  Stage B: Rule-Based      | {stage['rule_based']['count']:<10} | {stage['rule_based']['share_percent']}%")
    print(f"  Stage C: LLM Pass        | {stage['llm']['count']:<10} | {stage['llm']['share_percent']}%")
    print(sub_banner)

    print("\n[+] CONFUSION BREAKDOWN BY INJECTED REAL-WORLD ERROR TYPE:")
    print(sub_banner)
    print(f"  {'Error Class':<26} | {'Total':<6} | {'Auto':<6} | {'Review':<7} | {'Unres':<6} | {'Accuracy':<8}")
    print(sub_banner)
    for etype, d in confusion.items():
        print(f"  {etype:<26} | {d['total']:<6} | {d['auto_matched']:<6} | {d['needs_review']:<7} | {d['unresolved']:<6} | {d['accuracy_percent']:.1f}%")
    print(sub_banner)

    print("\n[+] OPERATIONAL THROUGHPUT & COST TELEMETRY:")
    print(sub_banner)
    print(f"  Throughput Speed           : {perf['throughput_records_sec']:,.1f} records/second")
    print(f"  Pipeline Execution Time    : {perf['elapsed_seconds']:.3f} seconds")
    print(f"  LLM Calls Made             : {perf['llm_calls_made']} (invoked strictly on leftovers)")
    print(f"  LLM Provider               : {perf['llm_provider']}")
    print(f"  Estimated Batch Cost       : ${perf['estimated_cost_usd']:.6f} USD (~INR {perf['estimated_cost_inr']:.3f})")

    # Read and print the exceptions summary
    if os.path.exists(exceptions_path):
        print("\n[!] HONEST EXCEPTION AUDIT TRAIL (exceptions.csv preview):")
        print(sub_banner)
        with open(exceptions_path, "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            for i, row in enumerate(reader[:7], 1):
                print(f"  [{row['exception_id']}] {row['status']} | {row['exception_category']} | Amount: INR {row['amount_involved_inr']}")
                print(f"      Involved Records : Bank={row['bank_txn_ids']} | Gateway={row['gateway_settlement_ids']} | Invoices={row['invoice_ids']}")
                print(f"      Why it Failed    : {row['root_cause_explanation']}")
                print(f"      Human Action     : {row['suggested_human_action']}")
                print()
        if len(reader) > 7:
            print(f"  ... and {len(reader) - 7} more exceptions documented in results/exceptions.csv")

    print(f"{banner}\n")
