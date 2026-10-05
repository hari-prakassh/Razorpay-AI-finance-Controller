"""
Synthetic Financial Data Generator with Ground Truth.
Generates realistic Indian multi-source financial records:
1. Bank Statements (HDFC, ICICI, AXIS style narrations & UTRs)
2. Payment Gateway Settlement Report (Razorpay style MDR fees, GST, net payouts)
3. Internal Ledger / Invoices (B2B/B2C, TDS Sec 194J/194C, customer orders)
4. Hidden Ground Truth mapping all records to true matches with error types
"""

import csv
import os
import random
from datetime import datetime, timedelta
from typing import Dict, List, Tuple


INDIAN_BANKS = ["HDFC Bank", "ICICI Bank", "Axis Bank", "State Bank of India"]
CUSTOMER_NAMES = [
    ("Swiggy Technologies Pvt Ltd", "B2B", 0.10),
    ("Zomato Media Ltd", "B2B", 0.10),
    ("Flipkart India Pvt Ltd", "B2B", 0.02),
    ("Tata Consultancy Services", "B2B", 0.10),
    ("Infosys Limited", "B2B", 0.10),
    ("Reliance Retail Ventures", "B2B", 0.02),
    ("Ananya Sharma", "B2C", 0.0),
    ("Rohan Verma", "B2C", 0.0),
    ("Pooja Nair", "B2C", 0.0),
    ("Vikram Aditya Singh", "B2C", 0.0),
    ("Kavita Sundaram", "B2C", 0.0),
    ("Arjun Patel", "B2C", 0.0),
    ("Delhivery Logistics Ltd", "B2B", 0.02),
    ("Pine Labs Pvt Ltd", "B2B", 0.10),
    ("Meera Krishnan", "B2C", 0.0),
]


def generate_utr(rng: random.Random, index: int, prefix: str = "42") -> str:
    """Generate realistic 12-digit Indian UTR."""
    suffix = str(index).zfill(6)
    random_digits = "".join(rng.choices("0123456789", k=4))
    return f"{prefix}{random_digits}{suffix}"


def generate_synthetic_dataset(output_dir: str = "data", seed: int = 42) -> Dict[str, int]:
    """Generates synthetic dataset with known ground truth."""
    rng = random.Random(seed)
    os.makedirs(output_dir, exist_ok=True)

    base_date = datetime(2026, 9, 1)

    bank_records: List[Dict] = []
    gateway_records: List[Dict] = []
    ledger_records: List[Dict] = []
    ground_truth_records: List[Dict] = []

    group_counter = 1
    bank_counter = 1001
    gw_counter = 5001
    inv_counter = 2001

    running_bank_balance = 5_420_000.00

    def add_bank(dt: datetime, narration: str, deposit: float, utr: str, bank: str) -> str:
        nonlocal bank_counter, running_bank_balance
        bid = f"BNK-TXN-{bank_counter}"
        bank_counter += 1
        running_bank_balance += deposit
        bank_records.append({
            "bank_txn_id": bid,
            "txn_date": dt.strftime("%Y-%m-%d"),
            "narration": narration,
            "deposit_inr": round(deposit, 2),
            "withdrawal_inr": 0.00,
            "balance_inr": round(running_bank_balance, 2),
            "utr_number": utr,
            "bank_name": bank
        })
        return bid

    def add_gateway(dt: datetime, pid: str, oid: str, method: str,
                    gross: float, fee_rate: float, utr: str, status: str = "settled") -> Tuple[str, float]:
        nonlocal gw_counter
        gid = f"SET-{gw_counter}"
        gw_counter += 1
        fee = round(gross * fee_rate, 2)
        gst = round(fee * 0.18, 2) if fee > 0 else 0.0
        net = round(gross - (fee + gst), 2)
        gateway_records.append({
            "settlement_id": gid,
            "settlement_date": dt.strftime("%Y-%m-%d"),
            "payment_id": pid,
            "order_id": oid,
            "method": method,
            "gross_amount_inr": round(gross, 2),
            "fee_inr": fee,
            "tax_gst_inr": gst,
            "net_amount_inr": net,
            "utr_number": utr,
            "status": status
        })
        return gid, net

    def add_ledger(dt: datetime, cust: Tuple[str, str, float], gross: float,
                   order_ref: str, status: str = "paid") -> Tuple[str, float]:
        nonlocal inv_counter
        iid = f"INV-2026-{inv_counter}"
        inv_counter += 1
        cust_name, cust_type, tds_rate = cust
        tds_amt = round(gross * tds_rate, 2)
        expected_net = round(gross - tds_amt, 2)
        due_dt = dt + timedelta(days=15)
        ledger_records.append({
            "invoice_id": iid,
            "invoice_date": dt.strftime("%Y-%m-%d"),
            "customer_name": cust_name,
            "customer_type": cust_type,
            "gross_amount_inr": round(gross, 2),
            "tds_rate_percent": round(tds_rate * 100, 1),
            "tds_amount_inr": tds_amt,
            "expected_net_inr": expected_net,
            "order_ref": order_ref,
            "due_date": due_dt.strftime("%Y-%m-%d"),
            "status": status
        })
        return iid, expected_net

    def add_ground_truth(gid_str: str, b_ids: List[str], g_ids: List[str], i_ids: List[str],
                         category: str, error_type: str, decision: str, true_amt: float, notes: str):
        ground_truth_records.append({
            "match_group_id": gid_str,
            "bank_txn_ids": ";".join(b_ids),
            "gateway_settlement_ids": ";".join(g_ids),
            "invoice_ids": ";".join(i_ids),
            "match_category": category,
            "injected_error_type": error_type,
            "expected_decision": decision,
            "true_amount_inr": round(true_amt, 2),
            "notes": notes
        })

    # =========================================================================
    # 1. CLEAN EXACT MATCHES (~60% = 48 records)
    # =========================================================================
    for i in range(48):
        grp_id = f"GRP-{str(group_counter).zfill(3)}"
        group_counter += 1
        day_offset = rng.randint(1, 20)
        t_date = base_date + timedelta(days=day_offset)
        bank_date = t_date + timedelta(days=1)  # T+1

        cust = rng.choice(CUSTOMER_NAMES)
        is_upi = (cust[1] == "B2C") or rng.random() > 0.4
        method = "UPI" if is_upi else "credit_card"
        fee_rate = 0.0 if is_upi else 0.02

        gross = round(rng.uniform(1500, 85000), 2)
        if cust[1] == "B2B" and cust[2] > 0:
            # If B2B with TDS, gateway might not be involved OR gateway processes post-TDS
            # For 3-way clean match, invoice gross == gateway gross, B2C or zero-TDS B2B
            cust = (cust[0], "B2B", 0.0)

        pid = f"pay_RZP{str(i+100).zfill(4)}"
        oid = f"order_ORD{str(i+100).zfill(4)}"
        utr = generate_utr(rng, i + 100)
        bank_name = rng.choice(INDIAN_BANKS)

        lid, expected_net = add_ledger(t_date, cust, gross, oid)
        gid, net_payout = add_gateway(t_date, pid, oid, method, gross, fee_rate, utr)

        # Narration style
        if is_upi:
            narration = f"UPI/CR/{utr}/PYMT/Razorpay Soft/{pid}/NODAL"
        else:
            narration = f"CMS/RAZORPAYPAYMENTS/{utr}/SETTL/{pid}"

        bid = add_bank(bank_date, narration, net_payout, utr, bank_name)

        add_ground_truth(
            grp_id, [bid], [gid], [lid],
            "EXACT", "CLEAN_EXACT", "AUTO_MATCH",
            net_payout,
            f"Clean exact match. Net bank deposit ₹{net_payout} equals gateway net payout. UTR {utr} verified."
        )

    # =========================================================================
    # 2. FUZZY MATCHES (~15% = 12 records)
    # Truncated narration, formatted references, missing hyphens, case changes
    # =========================================================================
    fuzzy_styles = [
        "truncated_narration",
        "missing_hyphen_order_ref",
        "leading_zero_omitted",
        "lowercase_utr",
        "bank_prefix_cms_variation",
        "alphanumeric_neft_spacing"
    ]

    for i in range(12):
        grp_id = f"GRP-{str(group_counter).zfill(3)}"
        group_counter += 1
        style = fuzzy_styles[i % len(fuzzy_styles)]

        day_offset = rng.randint(2, 22)
        t_date = base_date + timedelta(days=day_offset)
        bank_date = t_date + timedelta(days=1)

        cust = rng.choice(CUSTOMER_NAMES)
        gross = round(rng.uniform(3000, 60000), 2)
        pid = f"pay_FZ{str(i+200).zfill(4)}"
        oid = f"order_FZ{str(i+200).zfill(4)}"
        utr = generate_utr(rng, i + 300)
        bank_name = rng.choice(INDIAN_BANKS)

        # Ledger order ref variation
        if style == "missing_hyphen_order_ref":
            ledger_order_ref = oid.replace("_", "")
        else:
            ledger_order_ref = oid

        lid, _ = add_ledger(t_date, (cust[0], cust[1], 0.0), gross, ledger_order_ref)
        gid, net_payout = add_gateway(t_date, pid, oid, "UPI", gross, 0.0, utr)

        # Bank narration variations
        if style == "truncated_narration":
            # Narration truncated to 28 characters
            full_narr = f"UPI/CR/{utr}/RAZORPAYSOFTWAREPRIVATE"
            narration = full_narr[:26] + ".."
            bank_utr = utr
        elif style == "leading_zero_omitted":
            narration = f"CMS/RAZORPAY/{utr.lstrip('0')}/SETTLEMENT"
            bank_utr = utr.lstrip('0')
        elif style == "lowercase_utr":
            narration = f"neft-razorpay-{utr.lower()}-{pid}"
            bank_utr = utr.lower()
        elif style == "bank_prefix_cms_variation":
            narration = f"CMS-DEP-RZP-IND-{utr}-{oid}"
            bank_utr = utr
        elif style == "alphanumeric_neft_spacing":
            narration = f"NEFT / {bank_name[:4].upper()} / {utr} / RAZORPAY / {pid}"
            bank_utr = utr
        else:
            narration = f"UPI/CR/{utr}/PYMT/Razorpay/{pid}"
            bank_utr = utr

        bid = add_bank(bank_date, narration, net_payout, bank_utr, bank_name)

        add_ground_truth(
            grp_id, [bid], [gid], [lid],
            "FUZZY", "FUZZY_REFERENCE", "AUTO_MATCH",
            net_payout,
            f"Fuzzy match with {style}. References reconcile under regex normalization and amount alignment."
        )

    # =========================================================================
    # 3. AMOUNT MISMATCHES: GATEWAY FEES / TDS / ROUNDING (~8.75% = 7 records)
    # =========================================================================
    amount_mismatch_types = [
        ("MDR_CARD_FEE_UNADJUSTED", "Gateway deducted 2% MDR + 18% GST; ledger recorded full gross amount"),
        ("TDS_194J_DEDUCTED", "B2B client deducted 10% TDS under Sec 194J; bank shows net receipt"),
        ("TDS_194C_DEDUCTED", "B2B client deducted 2% TDS under Sec 194C; bank shows net receipt"),
        ("PAISE_ROUNDING_OFF", "Fractional paise rounding difference of ₹0.68 between gateway & bank"),
        ("MDR_NETBANKING_FEE", "Gateway deducted 1.8% Netbanking fee + 18% GST"),
        ("TDS_AND_FEE_COMBINED", "Both 10% TDS and gateway processing fee applied"),
        ("UNAUTHORIZED_SHORT_PAYMENT", "Customer short-paid by ₹500 without valid deduction reason"),
    ]

    for i, (mtype, mdesc) in enumerate(amount_mismatch_types):
        grp_id = f"GRP-{str(group_counter).zfill(3)}"
        group_counter += 1

        day_offset = rng.randint(3, 24)
        t_date = base_date + timedelta(days=day_offset)
        bank_date = t_date + timedelta(days=1)
        gross = round(rng.uniform(25000, 150000), 2)
        pid = f"pay_AMT{str(i+300).zfill(4)}"
        oid = f"order_AMT{str(i+300).zfill(4)}"
        utr = generate_utr(rng, i + 500)
        bank_name = rng.choice(INDIAN_BANKS)

        expected_dec = "AUTO_MATCH"
        if mtype == "MDR_CARD_FEE_UNADJUSTED":
            # Ledger expects full gross, gateway deducts 2% + 18% GST (2.36%)
            lid, _ = add_ledger(t_date, ("Tata Consultancy Services", "B2B", 0.0), gross, oid)
            gid, net_payout = add_gateway(t_date, pid, oid, "credit_card", gross, 0.02, utr)
            bid = add_bank(bank_date, f"CMS/RAZORPAYPAYMENTS/{utr}/{pid}", net_payout, utr, bank_name)
            true_amt = net_payout

        elif mtype == "TDS_194J_DEDUCTED":
            # 10% TDS
            tds_val = round(gross * 0.10, 2)
            net_after_tds = round(gross - tds_val, 2)
            lid, _ = add_ledger(t_date, ("Infosys Limited", "B2B", 0.10), gross, oid)
            gid, _ = add_gateway(t_date, pid, oid, "NEFT", net_after_tds, 0.0, utr)
            bid = add_bank(bank_date, f"NEFT-UTIB000123-INFOSYS-INV-TDS194J-{utr}", net_after_tds, utr, bank_name)
            true_amt = net_after_tds

        elif mtype == "TDS_194C_DEDUCTED":
            # 2% TDS
            tds_val = round(gross * 0.02, 2)
            net_after_tds = round(gross - tds_val, 2)
            lid, _ = add_ledger(t_date, ("Reliance Retail Ventures", "B2B", 0.02), gross, oid)
            gid, _ = add_gateway(t_date, pid, oid, "NEFT", net_after_tds, 0.0, utr)
            bid = add_bank(bank_date, f"NEFT-HDFC000045-RELIANCE-INV-{utr}", net_after_tds, utr, bank_name)
            true_amt = net_after_tds

        elif mtype == "PAISE_ROUNDING_OFF":
            lid, _ = add_ledger(t_date, ("Rohan Verma", "B2C", 0.0), gross, oid)
            gid, net_payout = add_gateway(t_date, pid, oid, "UPI", gross, 0.0, utr)
            rounded_deposit = round(net_payout + 0.68, 2)
            bid = add_bank(bank_date, f"UPI/CR/{utr}/PYMT/Razorpay/{pid}", rounded_deposit, utr, bank_name)
            true_amt = rounded_deposit

        elif mtype == "MDR_NETBANKING_FEE":
            lid, _ = add_ledger(t_date, ("Swiggy Technologies Pvt Ltd", "B2B", 0.0), gross, oid)
            gid, net_payout = add_gateway(t_date, pid, oid, "netbanking", gross, 0.018, utr)
            bid = add_bank(bank_date, f"CMS/RAZORPAY/{utr}/{pid}", net_payout, utr, bank_name)
            true_amt = net_payout

        elif mtype == "TDS_AND_FEE_COMBINED":
            # 10% TDS on gross, then gateway fee on net
            tds_val = round(gross * 0.10, 2)
            after_tds = gross - tds_val
            lid, _ = add_ledger(t_date, ("Zomato Media Ltd", "B2B", 0.10), gross, oid)
            gid, net_payout = add_gateway(t_date, pid, oid, "corporate_card", after_tds, 0.02, utr)
            bid = add_bank(bank_date, f"CMS/RAZORPAYPAYMENTS/{utr}/{pid}", net_payout, utr, bank_name)
            true_amt = net_payout

        else:  # UNAUTHORIZED_SHORT_PAYMENT
            lid, _ = add_ledger(t_date, ("Flipkart India Pvt Ltd", "B2B", 0.0), gross, oid)
            short_payout = round(gross - 500.00, 2)
            gid, _ = add_gateway(t_date, pid, oid, "UPI", short_payout, 0.0, utr)
            bid = add_bank(bank_date, f"NEFT-FLIPKART-DISCREPANT-{utr}", short_payout, utr, bank_name)
            true_amt = short_payout
            expected_dec = "NEEDS_REVIEW"

        add_ground_truth(
            grp_id, [bid], [gid], [lid],
            "FEE_TDS", "FEE_TDS_AMOUNT_MISMATCH", expected_dec,
            true_amt,
            f"{mdesc}. Reconciliation requires statutory tax/MDR formula verification."
        )

    # =========================================================================
    # 4. DATE DRIFT (~5% = 4 records)
    # T+3 to T+5 days settlement lag across weekend and bank holiday
    # =========================================================================
    for i in range(4):
        grp_id = f"GRP-{str(group_counter).zfill(3)}"
        group_counter += 1

        day_offset = 5 + (i * 4)
        t_date = base_date + timedelta(days=day_offset)
        # Settle 4 days later (Friday -> Tuesday)
        drift_days = rng.choice([3, 4, 5])
        bank_date = t_date + timedelta(days=drift_days)

        gross = round(rng.uniform(5000, 45000), 2)
        pid = f"pay_DFT{str(i+400).zfill(4)}"
        oid = f"order_DFT{str(i+400).zfill(4)}"
        utr = generate_utr(rng, i + 700)
        bank_name = rng.choice(INDIAN_BANKS)

        lid, _ = add_ledger(t_date, ("Ananya Sharma", "B2C", 0.0), gross, oid)
        gid, net_payout = add_gateway(t_date, pid, oid, "UPI", gross, 0.0, utr)
        narration = f"UPI/CR/{utr}/PYMT/Razorpay Soft/{pid}/HOLIDAY_DELAY"
        bid = add_bank(bank_date, narration, net_payout, utr, bank_name)

        add_ground_truth(
            grp_id, [bid], [gid], [lid],
            "DATE_DRIFT", "DATE_DRIFT", "AUTO_MATCH",
            net_payout,
            f"Settlement lagged by {drift_days} calendar days due to banking holiday weekend. Identifiers and amount match perfectly."
        )

    # =========================================================================
    # 5. DUPLICATES (~3.75% = 3 records)
    # Webhook replay / duplicate credit attempt
    # =========================================================================
    for i in range(3):
        grp_id = f"GRP-{str(group_counter).zfill(3)}"
        group_counter += 1

        day_offset = 12 + i
        t_date = base_date + timedelta(days=day_offset)
        bank_date = t_date + timedelta(days=1)

        gross = round(rng.uniform(8000, 32000), 2)
        pid = f"pay_DUP{str(i+500).zfill(4)}"
        oid = f"order_DUP{str(i+500).zfill(4)}"
        utr = generate_utr(rng, i + 800)
        bank_name = rng.choice(INDIAN_BANKS)

        lid, _ = add_ledger(t_date, ("Vikram Aditya Singh", "B2C", 0.0), gross, oid)
        gid1, net1 = add_gateway(t_date, pid, oid, "UPI", gross, 0.0, utr)

        # Duplicate gateway entry or duplicate bank entry
        if i == 0:
            # Duplicate gateway settlement line (webhook retry replay)
            gid2, _ = add_gateway(t_date + timedelta(hours=2), pid, oid, "UPI", gross, 0.0, utr)
            bid = add_bank(bank_date, f"UPI/CR/{utr}/PYMT/Razorpay/{pid}", net1, utr, bank_name)
            add_ground_truth(
                grp_id, [bid], [gid1, gid2], [lid],
                "DUPLICATE", "DUPLICATE", "NEEDS_REVIEW",
                net1,
                "Webhook replay duplicate detected in gateway. Only one bank credit exists for duplicate settlement records."
            )
        elif i == 1:
            # Duplicate bank credit (bank system glitch credited twice)
            bid1 = add_bank(bank_date, f"UPI/CR/{utr}/PYMT/Razorpay/{pid}", net1, utr, bank_name)
            bid2 = add_bank(bank_date, f"UPI/CR/{utr}/PYMT/Razorpay/{pid}/RETRY", net1, utr, bank_name)
            add_ground_truth(
                grp_id, [bid1, bid2], [gid1], [lid],
                "DUPLICATE", "DUPLICATE", "NEEDS_REVIEW",
                net1,
                "Double bank credit anomaly: Bank credited twice for single gateway settlement. Flagged for clawback/reversal."
            )
        else:
            # Duplicate invoice raised in ledger
            lid2, _ = add_ledger(t_date, ("Vikram Aditya Singh", "B2C", 0.0), gross, oid)
            bid = add_bank(bank_date, f"UPI/CR/{utr}/PYMT/Razorpay/{pid}", net1, utr, bank_name)
            add_ground_truth(
                grp_id, [bid], [gid1], [lid, lid2],
                "DUPLICATE", "DUPLICATE", "NEEDS_REVIEW",
                net1,
                "Duplicate internal invoice issued for same order. Single payment received."
            )

    # =========================================================================
    # 6. SPLIT / MERGED BATCH PAYMENTS (~3.75% = 3 records)
    # Razorpay 1 Bank Payout lump-sum = Multiple Gateway Transactions
    # =========================================================================
    for i in range(3):
        grp_id = f"GRP-{str(group_counter).zfill(3)}"
        group_counter += 1

        day_offset = 15 + i
        t_date = base_date + timedelta(days=day_offset)
        bank_date = t_date + timedelta(days=1)

        batch_utr = generate_utr(rng, i + 900, prefix="55")
        bank_name = rng.choice(INDIAN_BANKS)

        # 2 orders bundled in 1 payout batch
        gross1 = round(rng.uniform(10000, 25000), 2)
        gross2 = round(rng.uniform(12000, 30000), 2)

        pid1 = f"pay_SPL1_{str(i).zfill(2)}"
        pid2 = f"pay_SPL2_{str(i).zfill(2)}"
        oid1 = f"order_SPL1_{str(i).zfill(2)}"
        oid2 = f"order_SPL2_{str(i).zfill(2)}"

        lid1, _ = add_ledger(t_date, ("Delhivery Logistics Ltd", "B2B", 0.0), gross1, oid1)
        lid2, _ = add_ledger(t_date, ("Pooja Nair", "B2C", 0.0), gross2, oid2)

        gid1, net1 = add_gateway(t_date, pid1, oid1, "card", gross1, 0.02, batch_utr)
        gid2, net2 = add_gateway(t_date, pid2, oid2, "UPI", gross2, 0.0, batch_utr)

        batch_deposit = round(net1 + net2, 2)
        narration = f"CMS/RAZORPAYPAYMENTS/{batch_utr}/BATCH_NODAL_{pid1[:6]}"
        bid = add_bank(bank_date, narration, batch_deposit, batch_utr, bank_name)

        add_ground_truth(
            grp_id, [bid], [gid1, gid2], [lid1, lid2],
            "SPLIT_MERGED", "SPLIT_MERGED", "AUTO_MATCH",
            batch_deposit,
            f"Batch settlement payout: 1 bank line (₹{batch_deposit}) aggregates 2 gateway transactions (₹{net1} + ₹{net2})."
        )

    # =========================================================================
    # 7. TRULY UNMATCHED (~3.75% = 3 records)
    # 1 orphan bank line, 1 orphan gateway line, 1 orphan ledger line
    # =========================================================================
    # 7a. Orphan Bank line (e.g. unknown direct bank credit / chargeback fee)
    grp_id_bank = f"GRP-{str(group_counter).zfill(3)}"
    group_counter += 1
    unmatched_b_utr = generate_utr(rng, 991, prefix="99")
    bid_unmatched = add_bank(
        base_date + timedelta(days=26),
        f"NEFT-DIRECT-UNIDENTIFIED-CREDIT-{unmatched_b_utr}",
        18500.00,
        unmatched_b_utr,
        "HDFC Bank"
    )
    add_ground_truth(
        grp_id_bank, [bid_unmatched], [], [],
        "UNMATCHED", "TRULY_UNMATCHED", "UNRESOLVED",
        18500.00,
        "Unidentified bank credit without matching gateway transaction or invoice. Potential suspense account entry."
    )

    # 7b. Orphan Gateway Settlement (settled in nodal, but nodal bank transfer pending/failed)
    grp_id_gw = f"GRP-{str(group_counter).zfill(3)}"
    group_counter += 1
    orphan_pid = "pay_ORPHAN_NODAL_992"
    orphan_oid = "order_ORPHAN_992"
    gid_unmatched, net_orphan = add_gateway(
        base_date + timedelta(days=27),
        orphan_pid, orphan_oid, "UPI", 14200.00, 0.0,
        generate_utr(rng, 992, prefix="99"),
        status="settled"
    )
    add_ground_truth(
        grp_id_gw, [], [gid_unmatched], [],
        "UNMATCHED", "TRULY_UNMATCHED", "UNRESOLVED",
        net_orphan,
        "Gateway settlement reported as nodal-settled, but absent from bank statement (unsettled gateway float)."
    )

    # 7c. Orphan Invoice (Issued invoice unpaid / customer defaulted)
    grp_id_inv = f"GRP-{str(group_counter).zfill(3)}"
    group_counter += 1
    lid_unmatched, net_inv = add_ledger(
        base_date + timedelta(days=28),
        ("Pine Labs Pvt Ltd", "B2B", 0.10),
        75000.00,
        "order_DEBTOR_UNPAID_993",
        status="overdue"
    )
    add_ground_truth(
        grp_id_inv, [], [], [lid_unmatched],
        "UNMATCHED", "TRULY_UNMATCHED", "UNRESOLVED",
        net_inv,
        "Internal invoice unpaid. No payment gateway settlement or bank credit ever received."
    )

    # Save to CSV files
    _save_csv(os.path.join(output_dir, "bank_statement.csv"), bank_records)
    _save_csv(os.path.join(output_dir, "gateway_settlements.csv"), gateway_records)
    _save_csv(os.path.join(output_dir, "internal_ledger.csv"), ledger_records)
    _save_csv(os.path.join(output_dir, "ground_truth.csv"), ground_truth_records)

    return {
        "bank_records_count": len(bank_records),
        "gateway_records_count": len(gateway_records),
        "ledger_records_count": len(ledger_records),
        "ground_truth_groups_count": len(ground_truth_records)
    }


def _save_csv(filepath: str, data: List[Dict]):
    """Helper to save a list of dicts to CSV."""
    if not data:
        return
    fieldnames = list(data[0].keys())
    with open(filepath, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)


if __name__ == "__main__":
    stats = generate_synthetic_dataset()
    print("Dataset generated successfully:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
