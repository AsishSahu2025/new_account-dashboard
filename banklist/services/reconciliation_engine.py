# banklist/services/reconciliation_engine.py
"""
Reconciliation Engine
Matches transactions across two bank accounts.

Matching logic (priority order):
  1. Exact UTR match    → Matched (strongest)
  2. Amount + Date (±1 day) → Matched
  3. No match           → Unmatched

Usage:
    from banklist.services.reconciliation_engine import run_reconciliation
    result = run_reconciliation(bank_account_1_id, bank_account_2_id, company_id)
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.db import transaction as db_transaction

logger = logging.getLogger(__name__)


def run_reconciliation(bank_account_1_id: int, bank_account_2_id: int,
                       company_id: int, date_from=None, date_to=None) -> dict:
    """
    Run reconciliation between two bank accounts.

    Args:
        bank_account_1_id: Primary bank account (e.g., SBI)
        bank_account_2_id: Secondary bank account (e.g., DBS)
        company_id: Company ID for security check
        date_from: Optional start date filter
        date_to: Optional end date filter

    Returns:
        dict with matched_count, unmatched_count, total, details
    """
    # Import here to avoid circular imports
    from banklist.models import Transaction, BankAccount

    # Verify both accounts belong to company
    try:
        acc1 = BankAccount.objects.get(id=bank_account_1_id, company_id=company_id)
        acc2 = BankAccount.objects.get(id=bank_account_2_id, company_id=company_id)
    except BankAccount.DoesNotExist:
        return {'error': 'Bank account not found or access denied'}

    # Fetch transactions
    qs1 = Transaction.objects.filter(
        bank_account=acc1, company_id=company_id
    )
    qs2 = Transaction.objects.filter(
        bank_account=acc2, company_id=company_id
    )
    if date_from:
        qs1 = qs1.filter(txn_date__gte=date_from)
        qs2 = qs2.filter(txn_date__gte=date_from)
    if date_to:
        qs1 = qs1.filter(txn_date__lte=date_to)
        qs2 = qs2.filter(txn_date__lte=date_to)

    txns1 = list(qs1)
    txns2 = list(qs2)

    # Reset all previous reconciliation status for these accounts in range
    _reset_reconciliation(txns1 + txns2)

    # Index txns2 for fast lookup
    # UTR index: utr_no → list of txns
    utr_index = {}
    # Amount+Date index: (amount, date) → list of txns
    amount_date_index = {}

    for txn in txns2:
        if txn.utr_no:
            utr_index.setdefault(txn.utr_no, []).append(txn)
        key = (txn.amount, txn.txn_date)
        amount_date_index.setdefault(key, []).append(txn)

    matched_pairs = []
    unmatched1 = []

    used_txns2 = set()  # prevent double-matching

    for txn1 in txns1:
        matched_txn2 = None

        # Priority 1: UTR match
        if txn1.utr_no:
            candidates = utr_index.get(txn1.utr_no, [])
            for c in candidates:
                if c.id not in used_txns2:
                    matched_txn2 = c
                    break

        # Priority 2: Amount + Date (±1 day)
        if not matched_txn2:
            matched_txn2 = _find_by_amount_date(
                txn1, txns2, used_txns2, tolerance_days=1
            )

        if matched_txn2:
            used_txns2.add(matched_txn2.id)
            matched_pairs.append((txn1, matched_txn2))
        else:
            unmatched1.append(txn1)

    # Transactions in txns2 not matched
    unmatched2 = [t for t in txns2 if t.id not in used_txns2]

    # Persist results
    _save_results(matched_pairs, unmatched1, unmatched2)

    stats = {
        'bank1': str(acc1),
        'bank2': str(acc2),
        'total_bank1': len(txns1),
        'total_bank2': len(txns2),
        'matched_count': len(matched_pairs),
        'unmatched_bank1': len(unmatched1),
        'unmatched_bank2': len(unmatched2),
        'match_rate': round(len(matched_pairs) / max(len(txns1), 1) * 100, 1),
    }

    logger.info(f"Reconciliation complete: {stats}")
    return stats


def _find_by_amount_date(txn1, txns2_list, used_ids, tolerance_days=1):
    """Find matching transaction by amount and date within tolerance."""
    for txn2 in txns2_list:
        if txn2.id in used_ids:
            continue
        if txn2.amount != txn1.amount:
            continue
        date_diff = abs((txn2.txn_date - txn1.txn_date).days)
        if date_diff <= tolerance_days:
            return txn2
    return None


def _reset_reconciliation(txns):
    """Reset reconciliation status before re-running."""
    ids = [t.id for t in txns]
    if ids:
        from banklist.models import Transaction
        Transaction.objects.filter(id__in=ids).update(
            reconcile_status='unmatched',
            matched_txn=None,
        )


@db_transaction.atomic
def _save_results(matched_pairs, unmatched1, unmatched2):
    """Persist reconciliation results to DB."""
    from banklist.models import Transaction

    for txn1, txn2 in matched_pairs:
        txn1.reconcile_status = 'matched'
        txn1.matched_txn = txn2
        txn1.save(update_fields=['reconcile_status', 'matched_txn'])

        txn2.reconcile_status = 'matched'
        txn2.matched_txn = txn1
        txn2.save(update_fields=['reconcile_status', 'matched_txn'])

    for txn in unmatched1 + unmatched2:
        txn.reconcile_status = 'unmatched'
        txn.save(update_fields=['reconcile_status'])