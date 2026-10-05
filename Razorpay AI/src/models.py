"""
Domain models for the Multi-Source Reconciliation Agent.
Sources:
1. Bank Statement Lines
2. Payment Gateway Settlement Report
3. Internal Ledger / Invoices
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class BankTransaction:
    bank_txn_id: str
    txn_date: str              # YYYY-MM-DD
    narration: str
    deposit_inr: float         # Credit into bank
    withdrawal_inr: float      # Debit
    balance_inr: float
    utr_number: str            # 12-digit or alphanumeric UTR
    bank_name: str             # e.g., HDFC, ICICI, AXIS
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GatewaySettlement:
    settlement_id: str         # e.g., set_1001
    settlement_date: str       # YYYY-MM-DD
    payment_id: str            # e.g., pay_N8a9...
    order_id: str              # e.g., order_K92...
    method: str                # UPI, card, netbanking
    gross_amount_inr: float
    fee_inr: float             # MDR fee
    tax_gst_inr: float         # 18% GST on fee
    net_amount_inr: float       # gross - (fee + tax)
    utr_number: str            # Bank settlement UTR
    status: str                # settled, failed, refunded
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InternalInvoice:
    invoice_id: str            # e.g., INV-2026-001
    invoice_date: str          # YYYY-MM-DD
    customer_name: str
    customer_id: str
    gross_amount_inr: float
    tds_rate_percent: float    # 0%, 2%, 10%
    tds_amount_inr: float
    expected_net_inr: float    # gross - tds
    order_ref: str             # linked order_id or payment_id
    due_date: str
    status: str                # paid, unpaid, overdue
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GroundTruthRecord:
    match_group_id: str
    bank_txn_ids: List[str]
    gateway_settlement_ids: List[str]
    invoice_ids: List[str]
    match_category: str        # EXACT, FUZZY, FEE_TDS, DATE_DRIFT, DUPLICATE, SPLIT_MERGED, UNMATCHED
    injected_error_type: str
    expected_decision: str     # AUTO_MATCH, NEEDS_REVIEW, UNRESOLVED
    true_amount_inr: float
    notes: str


@dataclass
class ReconciliationMatch:
    match_id: str
    status: str                # AUTO_MATCHED, NEEDS_REVIEW, UNRESOLVED
    stage: str                 # DETERMINISTIC, RULE_BASED, LLM, UNRESOLVED
    confidence: float          # 0.0 to 1.0
    bank_txn_ids: List[str] = field(default_factory=list)
    gateway_settlement_ids: List[str] = field(default_factory=list)
    invoice_ids: List[str] = field(default_factory=list)
    reconciled_amount: float = 0.0
    amount_discrepancy: float = 0.0
    reasoning: str = ""
    evidence_fields: List[str] = field(default_factory=list)
    rule_or_model: str = ""
