"""
Data loader for bank statements, gateway settlements, and internal invoices.
"""

import csv
import os
from typing import Dict, List, Tuple
from src.models import BankTransaction, GatewaySettlement, InternalInvoice, GroundTruthRecord


def load_dataset(data_dir: str = "data") -> Tuple[
    List[BankTransaction],
    List[GatewaySettlement],
    List[InternalInvoice],
    List[GroundTruthRecord]
]:
    """Loads all records from CSV files into domain objects."""
    bank_path = os.path.join(data_dir, "bank_statement.csv")
    gateway_path = os.path.join(data_dir, "gateway_settlements.csv")
    ledger_path = os.path.join(data_dir, "internal_ledger.csv")
    gt_path = os.path.join(data_dir, "ground_truth.csv")

    bank_records: List[BankTransaction] = []
    if os.path.exists(bank_path):
        with open(bank_path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                bank_records.append(BankTransaction(
                    bank_txn_id=row["bank_txn_id"],
                    txn_date=row["txn_date"],
                    narration=row["narration"],
                    deposit_inr=float(row["deposit_inr"]),
                    withdrawal_inr=float(row["withdrawal_inr"]),
                    balance_inr=float(row["balance_inr"]),
                    utr_number=row["utr_number"],
                    bank_name=row["bank_name"],
                    raw_data=row
                ))

    gateway_records: List[GatewaySettlement] = []
    if os.path.exists(gateway_path):
        with open(gateway_path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                gateway_records.append(GatewaySettlement(
                    settlement_id=row["settlement_id"],
                    settlement_date=row["settlement_date"],
                    payment_id=row["payment_id"],
                    order_id=row["order_id"],
                    method=row["method"],
                    gross_amount_inr=float(row["gross_amount_inr"]),
                    fee_inr=float(row["fee_inr"]),
                    tax_gst_inr=float(row["tax_gst_inr"]),
                    net_amount_inr=float(row["net_amount_inr"]),
                    utr_number=row["utr_number"],
                    status=row["status"],
                    raw_data=row
                ))

    ledger_records: List[InternalInvoice] = []
    if os.path.exists(ledger_path):
        with open(ledger_path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                ledger_records.append(InternalInvoice(
                    invoice_id=row["invoice_id"],
                    invoice_date=row["invoice_date"],
                    customer_name=row["customer_name"],
                    customer_id=row.get("customer_type", "B2C"),
                    gross_amount_inr=float(row["gross_amount_inr"]),
                    tds_rate_percent=float(row.get("tds_rate_percent", 0.0)),
                    tds_amount_inr=float(row.get("tds_amount_inr", 0.0)),
                    expected_net_inr=float(row["expected_net_inr"]),
                    order_ref=row["order_ref"],
                    due_date=row["due_date"],
                    status=row["status"],
                    raw_data=row
                ))

    ground_truth_records: List[GroundTruthRecord] = []
    if os.path.exists(gt_path):
        with open(gt_path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                b_ids = [x for x in row["bank_txn_ids"].split(";") if x]
                g_ids = [x for x in row["gateway_settlement_ids"].split(";") if x]
                i_ids = [x for x in row["invoice_ids"].split(";") if x]
                ground_truth_records.append(GroundTruthRecord(
                    match_group_id=row["match_group_id"],
                    bank_txn_ids=b_ids,
                    gateway_settlement_ids=g_ids,
                    invoice_ids=i_ids,
                    match_category=row["match_category"],
                    injected_error_type=row["injected_error_type"],
                    expected_decision=row["expected_decision"],
                    true_amount_inr=float(row["true_amount_inr"]),
                    notes=row["notes"]
                ))

    return bank_records, gateway_records, ledger_records, ground_truth_records
