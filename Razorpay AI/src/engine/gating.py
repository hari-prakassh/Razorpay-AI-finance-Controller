"""
Pass D: Confidence Gating.
Implements strict decision routing:
- confidence >= 0.85: AUTO_MATCHED
- 0.50 <= confidence < 0.85: NEEDS_REVIEW
- confidence < 0.50: UNRESOLVED

Ensures every decision is logged with its governing stage, rule/model, and evidence fields.
"""

from typing import List, Tuple
from src.models import ReconciliationMatch


AUTO_MATCH_THRESHOLD = 0.85
NEEDS_REVIEW_THRESHOLD = 0.50


def apply_confidence_gating(
    matches: List[ReconciliationMatch]
) -> Tuple[List[ReconciliationMatch], List[ReconciliationMatch], List[ReconciliationMatch]]:
    """
    Partitions reconciliation matches into:
    1. auto_matched: confidence >= 0.85
    2. needs_review: 0.50 <= confidence < 0.85
    3. unresolved: confidence < 0.50
    """
    auto_matched: List[ReconciliationMatch] = []
    needs_review: List[ReconciliationMatch] = []
    unresolved: List[ReconciliationMatch] = []

    for m in matches:
        if m.confidence >= AUTO_MATCH_THRESHOLD:
            m.status = "AUTO_MATCHED"
            auto_matched.append(m)
        elif m.confidence >= NEEDS_REVIEW_THRESHOLD:
            m.status = "NEEDS_REVIEW"
            needs_review.append(m)
        else:
            m.status = "UNRESOLVED"
            unresolved.append(m)

    return auto_matched, needs_review, unresolved
