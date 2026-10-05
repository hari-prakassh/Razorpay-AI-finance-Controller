"""
Pass A: Deterministic Matcher.
Executes exact 3-way matching on Reference ID (UTR / Payment ID) + Amount + Strict Date Window.
Confidence: 1.0.
Guards against duplicate bank lines, duplicate webhook settlements, and duplicate invoices.
"""

from collections import Counter
from datetime import datetime
from typing import Dict, List, Set, Tuple
from src.models import BankTransaction, GatewaySettlement, InternalInvoice, ReconciliationMatch


def run_deterministic_pass(
    bank_records: List[BankTransaction],
    gateway_records: List[GatewaySettlement],
    ledger_records: List[InternalInvoice]
) -> Tuple[
    List[ReconciliationMatch],
    List[BankTransaction],
    List[GatewaySettlement],
    List[InternalInvoice]
]:
    """
    Executes high-confidence exact deterministic pass.
    Matches across Bank, Gateway, and Ledger where:
    - Bank UTR == Gateway UTR (and neither is duplicated in source)
    - Bank Deposit == Gateway Net Amount (within 0.01 tolerance)
    - Gateway Date to Bank Date is within 0 to 2 days
    - Ledger Order Ref == Gateway Order ID or Payment ID (and not duplicated)
    - Ledger Expected Net == Gateway Gross or Net Amount (within 0.01 tolerance)
    """
    matches: List[ReconciliationMatch] = []

    matched_bank_ids: Set[str] = set()
    matched_gateway_ids: Set[str] = set()
    matched_ledger_ids: Set[str] = set()

    # Pre-detect duplicates in sources so deterministic pass doesn't blindly match them
    bank_utr_counts = Counter(b.utr_number.strip() for b in bank_records if b.utr_number)
    duplicate_bank_utrs = {utr for utr, count in bank_utr_counts.items() if count > 1}

    gw_utr_counts = Counter(g.utr_number.strip() for g in gateway_records if g.utr_number)
    duplicate_gw_utrs = {utr for utr, count in gw_utr_counts.items() if count > 1}

    gw_pid_counts = Counter(g.payment_id.strip() for g in gateway_records if g.payment_id)
    duplicate_gw_pids = {pid for pid, count in gw_pid_counts.items() if count > 1}

    ledger_order_counts = Counter(l.order_ref.strip() for l in ledger_records if l.order_ref)
    duplicate_ledger_orders = {ref for ref, count in ledger_order_counts.items() if count > 1}

    # Index gateways by UTR
    gateway_by_utr: Dict[str, List[GatewaySettlement]] = {}
    for g in gateway_records:
        if g.utr_number:
            gateway_by_utr.setdefault(g.utr_number.strip(), []).append(g)

    # Index ledgers by order_ref
    ledger_by_order: Dict[str, List[InternalInvoice]] = {}
    for l in ledger_records:
        if l.order_ref:
            ledger_by_order.setdefault(l.order_ref.strip(), []).append(l)

    match_counter = 1

    # Deterministic 3-way matching
    for b in bank_records:
        if b.bank_txn_id in matched_bank_ids:
            continue

        b_utr = b.utr_number.strip() if b.utr_number else ""
        if not b_utr or b_utr in duplicate_bank_utrs or b_utr in duplicate_gw_utrs:
            continue

        if b_utr not in gateway_by_utr:
            continue

        candidate_gateways = gateway_by_utr[b_utr]
        if len(candidate_gateways) != 1:
            continue

        g = candidate_gateways[0]
        if g.settlement_id in matched_gateway_ids or g.payment_id in duplicate_gw_pids:
            continue

        # Check exact net amount
        amount_diff = abs(b.deposit_inr - g.net_amount_inr)
        if amount_diff > 0.01:
            continue

        # Check strict date window (0 <= bank_date - settlement_date <= 2)
        days_lag = (datetime.strptime(b.txn_date, "%Y-%m-%d").date() -
                    datetime.strptime(g.settlement_date, "%Y-%m-%d").date()).days
        if not (0 <= days_lag <= 2):
            continue

        # Check if ledger order ref has duplicate invoice
        g_order = g.order_id.strip()
        g_pay = g.payment_id.strip()
        if g_order in duplicate_ledger_orders or g_pay in duplicate_ledger_orders:
            continue

        # Look for corresponding ledger invoice
        matching_invoices = ledger_by_order.get(g_order, [])
        if len(matching_invoices) != 1:
            matching_invoices = ledger_by_order.get(g_pay, [])

        if len(matching_invoices) == 1:
            inv = matching_invoices[0]
            if inv.invoice_id in matched_ledger_ids:
                continue

            # Check invoice amount compatibility
            inv_diff = abs(inv.gross_amount_inr - g.gross_amount_inr)
            inv_net_diff = abs(inv.expected_net_inr - g.net_amount_inr)
            if inv_diff <= 0.01 or inv_net_diff <= 0.01:
                # 3-Way Exact Match found!
                matched_bank_ids.add(b.bank_txn_id)
                matched_gateway_ids.add(g.settlement_id)
                matched_ledger_ids.add(inv.invoice_id)

                matches.append(ReconciliationMatch(
                    match_id=f"MATCH-DET-{str(match_counter).zfill(3)}",
                    status="AUTO_MATCHED",
                    stage="DETERMINISTIC",
                    confidence=1.0,
                    bank_txn_ids=[b.bank_txn_id],
                    gateway_settlement_ids=[g.settlement_id],
                    invoice_ids=[inv.invoice_id],
                    reconciled_amount=b.deposit_inr,
                    amount_discrepancy=0.0,
                    reasoning=f"Deterministic exact 3-way match: UTR {b_utr}, Net deposit INR {b.deposit_inr:.2f}, lag {days_lag}d.",
                    evidence_fields=["exact_utr", "exact_net_amount", "exact_order_ref", "settlement_lag_window"],
                    rule_or_model="deterministic_exact_3way"
                ))
                match_counter += 1

    remaining_bank = [b for b in bank_records if b.bank_txn_id not in matched_bank_ids]
    remaining_gateway = [g for g in gateway_records if g.settlement_id not in matched_gateway_ids]
    remaining_ledger = [l for l in ledger_records if l.invoice_id not in matched_ledger_ids]

    return matches, remaining_bank, remaining_gateway, remaining_ledger
