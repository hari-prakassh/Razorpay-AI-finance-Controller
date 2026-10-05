"""
Pass B: Rule-Based Domain Matcher.
Handles domain-specific Indian banking and gateway logic:
- Reference normalization & regex extraction (UTR, pay_*, order_*)
- Extended date drift tolerance (T+0 to T+5 days for weekends/holidays)
- MDR Fee (2% + 18% GST) and TDS (10% Sec 194J, 2% Sec 194C) reverse-calculation
- Penny / Paise rounding tolerance (<= 1.00 INR)
- Batch / Split settlement aggregation (1 bank deposit = multiple gateway lines)
- Duplicate anomaly detection (double bank credit, webhook replay, duplicate invoices)
- Unauthorized short payment detection
Confidence: 0.90 - 0.98 for confident matches; 0.65 - 0.75 for review items.
"""

import re
from collections import Counter
from datetime import datetime
from typing import Dict, List, Set, Tuple, Optional
from src.models import BankTransaction, GatewaySettlement, InternalInvoice, ReconciliationMatch


def clean_ref(s: str) -> str:
    """Normalize reference string for robust fuzzy matching."""
    if not s:
        return ""
    return re.sub(r"[^a-zA-Z0-9]", "", s).lower()


def extract_utr_from_narration(narration: str) -> Optional[str]:
    """Extract 12-digit Indian UTR from bank narration."""
    matches = re.findall(r"\b(\d{12})\b", narration)
    if matches:
        return matches[0]
    matches = re.findall(r"(?:UTR|CR|CMS|NEFT)[^\d]*(\d{10,16})", narration, re.IGNORECASE)
    if matches:
        return matches[0]
    return None


def extract_payment_id(narration: str) -> Optional[str]:
    m = re.search(r"(pay_[a-zA-Z0-9]+)", narration, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    return None


def extract_order_id(narration: str) -> Optional[str]:
    m = re.search(r"(order_[a-zA-Z0-9]+)", narration, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    return None


def run_rule_based_pass(
    bank_records: List[BankTransaction],
    gateway_records: List[GatewaySettlement],
    ledger_records: List[InternalInvoice]
) -> Tuple[
    List[ReconciliationMatch],
    List[BankTransaction],
    List[GatewaySettlement],
    List[InternalInvoice]
]:
    matches: List[ReconciliationMatch] = []
    matched_bank_ids: Set[str] = set()
    matched_gateway_ids: Set[str] = set()
    matched_ledger_ids: Set[str] = set()

    match_counter = 1

    # ---------------------------------------------------------
    # RULE 1: Duplicate Detection Anomaly Upfront
    # ---------------------------------------------------------
    # 1a. Duplicate Bank Credits (same UTR appears multiple times in bank statement)
    utr_bank_map: Dict[str, List[BankTransaction]] = {}
    for b in bank_records:
        if b.utr_number:
            utr_bank_map.setdefault(b.utr_number.strip(), []).append(b)

    for utr_val, b_list in utr_bank_map.items():
        if len(b_list) > 1:
            candidate_gw = [g for g in gateway_records if g.utr_number.strip() == utr_val]
            b_ids = [b.bank_txn_id for b in b_list]
            g_ids = [g.settlement_id for g in candidate_gw]

            inv_ids = []
            if candidate_gw:
                clean_oid = clean_ref(candidate_gw[0].order_id)
                inv_ids = [l.invoice_id for l in ledger_records if clean_ref(l.order_ref) == clean_oid]

            matched_bank_ids.update(b_ids)
            matched_gateway_ids.update(g_ids)
            matched_ledger_ids.update(inv_ids)

            matches.append(ReconciliationMatch(
                match_id=f"MATCH-RULE-DUP-{str(match_counter).zfill(3)}",
                status="NEEDS_REVIEW",
                stage="RULE_BASED",
                confidence=0.72,
                bank_txn_ids=b_ids,
                gateway_settlement_ids=g_ids,
                invoice_ids=inv_ids,
                reconciled_amount=b_list[0].deposit_inr,
                amount_discrepancy=round(b_list[0].deposit_inr * (len(b_list) - 1), 2),
                reasoning=f"Duplicate bank credit detected: UTR {utr_val} credited {len(b_list)} times in bank statement. Flagged for clawback/reversal investigation.",
                evidence_fields=["duplicate_utr_in_bank", "potential_double_credit"],
                rule_or_model="rule_duplicate_bank_credit_detector"
            ))
            match_counter += 1

    # 1b. Duplicate Gateway Settlement Records (Webhook Replay)
    gw_by_pid: Dict[str, List[GatewaySettlement]] = {}
    for g in gateway_records:
        if g.payment_id:
            gw_by_pid.setdefault(g.payment_id.strip(), []).append(g)

    for pid_val, g_list in gw_by_pid.items():
        if len(g_list) > 1:
            clean_g_utr = clean_ref(g_list[0].utr_number)
            b_cand = [
                b for b in bank_records
                if b.bank_txn_id not in matched_bank_ids and (
                    clean_ref(b.utr_number) == clean_g_utr or pid_val.lower() in b.narration.lower()
                )
            ]
            clean_oid = clean_ref(g_list[0].order_id)
            inv_cand = [
                l for l in ledger_records
                if l.invoice_id not in matched_ledger_ids and clean_ref(l.order_ref) == clean_oid
            ]

            b_ids = [b.bank_txn_id for b in b_cand]
            g_ids = [g.settlement_id for g in g_list]
            inv_ids = [l.invoice_id for l in inv_cand]

            matched_bank_ids.update(b_ids)
            matched_gateway_ids.update(g_ids)
            matched_ledger_ids.update(inv_ids)

            matches.append(ReconciliationMatch(
                match_id=f"MATCH-RULE-DUP-{str(match_counter).zfill(3)}",
                status="NEEDS_REVIEW",
                stage="RULE_BASED",
                confidence=0.75,
                bank_txn_ids=b_ids,
                gateway_settlement_ids=g_ids,
                invoice_ids=inv_ids,
                reconciled_amount=g_list[0].net_amount_inr,
                amount_discrepancy=0.0,
                reasoning=f"Webhook replay duplicate detected: Payment ID {pid_val} logged {len(g_list)} times in gateway report. Reconciled against single bank payout.",
                evidence_fields=["duplicate_payment_id_gateway", "webhook_replay_pattern"],
                rule_or_model="rule_duplicate_webhook_detector"
            ))
            match_counter += 1

    # 1c. Duplicate Invoices in Internal Ledger (Double Invoicing)
    ledger_order_map: Dict[str, List[InternalInvoice]] = {}
    for l in ledger_records:
        if l.order_ref:
            ledger_order_map.setdefault(clean_ref(l.order_ref), []).append(l)

    for o_ref, inv_list in ledger_order_map.items():
        if len(inv_list) > 1:
            candidate_gw = [
                g for g in gateway_records
                if g.settlement_id not in matched_gateway_ids and (
                    clean_ref(g.order_id) == o_ref or clean_ref(g.payment_id) == o_ref
                )
            ]
            b_cand = []
            if candidate_gw:
                g_utr = clean_ref(candidate_gw[0].utr_number)
                b_cand = [
                    b for b in bank_records
                    if b.bank_txn_id not in matched_bank_ids and clean_ref(b.utr_number) == g_utr
                ]

            b_ids = [b.bank_txn_id for b in b_cand]
            g_ids = [g.settlement_id for g in candidate_gw]
            inv_ids = [l.invoice_id for l in inv_list]

            matched_bank_ids.update(b_ids)
            matched_gateway_ids.update(g_ids)
            matched_ledger_ids.update(inv_ids)

            matches.append(ReconciliationMatch(
                match_id=f"MATCH-RULE-DUP-{str(match_counter).zfill(3)}",
                status="NEEDS_REVIEW",
                stage="RULE_BASED",
                confidence=0.70,
                bank_txn_ids=b_ids,
                gateway_settlement_ids=g_ids,
                invoice_ids=inv_ids,
                reconciled_amount=candidate_gw[0].net_amount_inr if candidate_gw else inv_list[0].expected_net_inr,
                amount_discrepancy=round(sum(l.expected_net_inr for l in inv_list[1:]), 2),
                reasoning=f"Duplicate internal invoice anomaly: {len(inv_list)} invoices ({', '.join(inv_ids)}) issued for same order '{o_ref}'. Only one payment received; credit note required.",
                evidence_fields=["duplicate_invoice_in_ledger", "single_payment_received"],
                rule_or_model="rule_duplicate_invoice_detector"
            ))
            match_counter += 1

    # ---------------------------------------------------------
    # RULE 2: Batch / Split Settlement Matching (1 Bank = N Gateways)
    # ---------------------------------------------------------
    gw_by_utr: Dict[str, List[GatewaySettlement]] = {}
    for g in gateway_records:
        if g.settlement_id not in matched_gateway_ids and g.utr_number:
            gw_by_utr.setdefault(g.utr_number.strip(), []).append(g)

    for b in bank_records:
        if b.bank_txn_id in matched_bank_ids:
            continue
        b_utr = b.utr_number.strip() if b.utr_number else extract_utr_from_narration(b.narration)
        if not b_utr:
            continue

        if b_utr in gw_by_utr and len(gw_by_utr[b_utr]) > 1:
            cluster = [g for g in gw_by_utr[b_utr] if g.settlement_id not in matched_gateway_ids]
            if len(cluster) > 1:
                cluster_sum = round(sum(g.net_amount_inr for g in cluster), 2)
                if abs(b.deposit_inr - cluster_sum) <= 1.00:
                    matched_bank_ids.add(b.bank_txn_id)
                    g_ids = [g.settlement_id for g in cluster]
                    matched_gateway_ids.update(g_ids)

                    inv_ids: List[str] = []
                    for g in cluster:
                        clean_g_oid = clean_ref(g.order_id)
                        for l in ledger_records:
                            if l.invoice_id not in matched_ledger_ids and l.invoice_id not in inv_ids:
                                if clean_ref(l.order_ref) == clean_g_oid or clean_ref(l.order_ref) == clean_ref(g.payment_id):
                                    inv_ids.append(l.invoice_id)
                                    matched_ledger_ids.add(l.invoice_id)
                                    break

                    matches.append(ReconciliationMatch(
                        match_id=f"MATCH-RULE-SPLIT-{str(match_counter).zfill(3)}",
                        status="AUTO_MATCHED",
                        stage="RULE_BASED",
                        confidence=0.95,
                        bank_txn_ids=[b.bank_txn_id],
                        gateway_settlement_ids=g_ids,
                        invoice_ids=inv_ids,
                        reconciled_amount=b.deposit_inr,
                        amount_discrepancy=round(abs(b.deposit_inr - cluster_sum), 2),
                        reasoning=f"Batch settlement rule: 1 bank line of INR {b.deposit_inr:.2f} matches sum of {len(cluster)} gateway transactions (INR {cluster_sum:.2f}) under batch UTR {b_utr}.",
                        evidence_fields=["batch_utr_aggregation", "sum_of_nets_equals_deposit", "multi_invoice_resolution"],
                        rule_or_model="rule_batch_settlement_aggregation"
                    ))
                    match_counter += 1

    # ---------------------------------------------------------
    # RULE 3: Normalized Reference, Date Drift, Fee/TDS, & Short Payment Matching
    # ---------------------------------------------------------
    for b in bank_records:
        if b.bank_txn_id in matched_bank_ids:
            continue

        b_utr_clean = clean_ref(b.utr_number)
        narration_clean = clean_ref(b.narration)
        narration_utr = extract_utr_from_narration(b.narration)
        narration_pid = extract_payment_id(b.narration)

        for g in gateway_records:
            if g.settlement_id in matched_gateway_ids:
                continue

            g_utr_clean = clean_ref(g.utr_number)
            g_pid_clean = clean_ref(g.payment_id)
            g_oid_clean = clean_ref(g.order_id)

            ref_matched = False
            ref_reason = ""

            if b_utr_clean and g_utr_clean and (b_utr_clean in g_utr_clean or g_utr_clean in b_utr_clean):
                ref_matched = True
                ref_reason = "cleaned_utr_match"
            elif narration_utr and clean_ref(narration_utr) == g_utr_clean:
                ref_matched = True
                ref_reason = "narration_extracted_utr"
            elif g_pid_clean and (g_pid_clean in narration_clean or (narration_pid and narration_pid in g_pid_clean)):
                ref_matched = True
                ref_reason = "narration_payment_id_match"
            elif g_oid_clean and g_oid_clean in narration_clean:
                ref_matched = True
                ref_reason = "narration_order_id_match"

            if not ref_matched:
                continue

            days_lag = (datetime.strptime(b.txn_date, "%Y-%m-%d").date() -
                        datetime.strptime(g.settlement_date, "%Y-%m-%d").date()).days
            if not (-1 <= days_lag <= 5):
                continue

            # Amount checking
            diff = abs(b.deposit_inr - g.net_amount_inr)
            amount_matched = False
            amount_reason = ""
            conf = 0.94

            expected_card_net = round(g.gross_amount_inr * (1.0 - 0.0236), 2)
            expected_nb_net = round(g.gross_amount_inr * (1.0 - 0.02124), 2)
            expected_tds_10 = round(g.gross_amount_inr * 0.90, 2)
            expected_tds_2 = round(g.gross_amount_inr * 0.98, 2)
            expected_tds_fee_comb = round((g.gross_amount_inr * 0.90) * (1.0 - 0.0236), 2)

            if diff <= 0.01:
                amount_matched = True
                amount_reason = f"exact_net_match_lag_{days_lag}d"
                conf = 0.96
            elif diff <= 1.00:
                amount_matched = True
                amount_reason = f"paise_rounding_diff_{diff:.2f}"
                conf = 0.95
            elif abs(b.deposit_inr - expected_card_net) <= 1.00:
                amount_matched = True
                amount_reason = "reconciled_mdr_card_fee_2_percent_plus_gst"
                conf = 0.94
            elif abs(b.deposit_inr - expected_nb_net) <= 1.00:
                amount_matched = True
                amount_reason = "reconciled_mdr_netbanking_fee_1.8_percent_plus_gst"
                conf = 0.94
            elif abs(b.deposit_inr - expected_tds_10) <= 1.00:
                amount_matched = True
                amount_reason = "reconciled_statutory_tds_10_percent_sec_194j"
                conf = 0.94
            elif abs(b.deposit_inr - expected_tds_2) <= 1.00:
                amount_matched = True
                amount_reason = "reconciled_statutory_tds_2_percent_sec_194c"
                conf = 0.94
            elif abs(b.deposit_inr - expected_tds_fee_comb) <= 1.00:
                amount_matched = True
                amount_reason = "reconciled_combined_tds_and_mdr_fee"
                conf = 0.92

            if amount_matched:
                # Find ledger record
                inv_match: Optional[InternalInvoice] = None
                for l in ledger_records:
                    if l.invoice_id in matched_ledger_ids:
                        continue
                    clean_l_ref = clean_ref(l.order_ref)
                    if clean_l_ref and (clean_l_ref == g_oid_clean or clean_l_ref == g_pid_clean or clean_l_ref in g_oid_clean or g_oid_clean in clean_l_ref):
                        inv_match = l
                        break

                inv_ids = [inv_match.invoice_id] if inv_match else []
                matched_bank_ids.add(b.bank_txn_id)
                matched_gateway_ids.add(g.settlement_id)
                if inv_match:
                    matched_ledger_ids.add(inv_match.invoice_id)

                # Check for unauthorized short payment against ledger invoice
                is_short_payment = False
                short_pay_diff = 0.0
                if inv_match:
                    # If invoice gross/net does not align with gateway/bank and exceeds tolerance
                    l_diff = abs(inv_match.expected_net_inr - b.deposit_inr)
                    if l_diff > 1.00 and abs(inv_match.expected_net_inr - g.gross_amount_inr) > 1.00:
                        # Check if diff is explained by TDS or fee
                        if not (abs(b.deposit_inr - expected_tds_10) <= 1.00 or
                                abs(b.deposit_inr - expected_tds_2) <= 1.00 or
                                abs(b.deposit_inr - expected_card_net) <= 1.00):
                            is_short_payment = True
                            short_pay_diff = l_diff

                if is_short_payment:
                    status = "NEEDS_REVIEW"
                    conf = 0.75
                    reason = f"Unauthorized short payment of INR {short_pay_diff:.2f} on invoice {inv_match.invoice_id} ({inv_match.customer_name}). Deposit INR {b.deposit_inr:.2f} vs Expected INR {inv_match.expected_net_inr:.2f}."
                    evidence = [ref_reason, "unauthorized_short_payment_detected", "ar_dispute_flag"]
                else:
                    status = "AUTO_MATCHED"
                    reason = f"Rule-based match: {ref_reason}, {amount_reason}, settlement lag {days_lag} days."
                    evidence = [ref_reason, amount_reason, "date_window_verified"]

                matches.append(ReconciliationMatch(
                    match_id=f"MATCH-RULE-{str(match_counter).zfill(3)}",
                    status=status,
                    stage="RULE_BASED",
                    confidence=conf,
                    bank_txn_ids=[b.bank_txn_id],
                    gateway_settlement_ids=[g.settlement_id],
                    invoice_ids=inv_ids,
                    reconciled_amount=b.deposit_inr,
                    amount_discrepancy=round(short_pay_diff if is_short_payment else diff, 2),
                    reasoning=reason,
                    evidence_fields=evidence,
                    rule_or_model="rule_reference_normalization_and_financial_tolerance"
                ))
                match_counter += 1
                break

    # ---------------------------------------------------------
    # RULE 4: Direct Ledger to Bank matching (Direct NEFT/RTGS)
    # ---------------------------------------------------------
    for b in bank_records:
        if b.bank_txn_id in matched_bank_ids:
            continue
        narration_clean = clean_ref(b.narration)

        for l in ledger_records:
            if l.invoice_id in matched_ledger_ids:
                continue
            clean_cust = clean_ref(l.customer_name)
            clean_oid = clean_ref(l.order_ref)

            name_token_match = any(token in narration_clean for token in clean_cust.split() if len(token) > 4)
            ref_token_match = (clean_oid and clean_oid in narration_clean)

            if name_token_match or ref_token_match:
                diff_net = abs(b.deposit_inr - l.expected_net_inr)
                tds_10_amt = round(l.gross_amount_inr * 0.90, 2)
                tds_2_amt = round(l.gross_amount_inr * 0.98, 2)

                if diff_net <= 1.00:
                    matched_bank_ids.add(b.bank_txn_id)
                    matched_ledger_ids.add(l.invoice_id)
                    matches.append(ReconciliationMatch(
                        match_id=f"MATCH-RULE-DIR-{str(match_counter).zfill(3)}",
                        status="AUTO_MATCHED",
                        stage="RULE_BASED",
                        confidence=0.92,
                        bank_txn_ids=[b.bank_txn_id],
                        gateway_settlement_ids=[],
                        invoice_ids=[l.invoice_id],
                        reconciled_amount=b.deposit_inr,
                        amount_discrepancy=round(diff_net, 2),
                        reasoning=f"Direct B2B payment reconciled: Bank narration matches customer '{l.customer_name}'. Expected net INR {l.expected_net_inr:.2f} matches deposit.",
                        evidence_fields=["direct_neft_match", "customer_name_narration", "expected_net_match"],
                        rule_or_model="rule_direct_b2b_ledger_match"
                    ))
                    match_counter += 1
                    break
                elif abs(b.deposit_inr - tds_10_amt) <= 1.00 or abs(b.deposit_inr - tds_2_amt) <= 1.00:
                    matched_bank_ids.add(b.bank_txn_id)
                    matched_ledger_ids.add(l.invoice_id)
                    matches.append(ReconciliationMatch(
                        match_id=f"MATCH-RULE-DIR-{str(match_counter).zfill(3)}",
                        status="AUTO_MATCHED",
                        stage="RULE_BASED",
                        confidence=0.91,
                        bank_txn_ids=[b.bank_txn_id],
                        gateway_settlement_ids=[],
                        invoice_ids=[l.invoice_id],
                        reconciled_amount=b.deposit_inr,
                        amount_discrepancy=round(abs(b.deposit_inr - l.gross_amount_inr), 2),
                        reasoning=f"Direct B2B payment with statutory TDS: Bank deposit matches invoice gross less Section 194J/194C TDS.",
                        evidence_fields=["direct_neft_match", "statutory_tds_calculated"],
                        rule_or_model="rule_direct_b2b_tds_match"
                    ))
                    match_counter += 1
                    break

    remaining_bank = [b for b in bank_records if b.bank_txn_id not in matched_bank_ids]
    remaining_gateway = [g for g in gateway_records if g.settlement_id not in matched_gateway_ids]
    remaining_ledger = [l for l in ledger_records if l.invoice_id not in matched_ledger_ids]

    return matches, remaining_bank, remaining_gateway, remaining_ledger
