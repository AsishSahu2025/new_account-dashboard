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
from banklist.models import Transaction, BankAccount, ReceiptDocument, ReconciliationRun

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
    # from banklist.models import
    # Transaction,
    # BankAccount,
    # ReceiptDocument,
    # ReconciliationRun

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
    # _reset_reconciliation(txns1 + txns2)

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
    receipt_missing = 0

    stats = {
        'bank1': str(acc1),
        'bank2': str(acc2),
        'total_bank1': len(txns1),
        'total_bank2': len(txns2),
        'matched_count': len(matched_pairs),
        "receipt_missing_count":receipt_missing,
        'unmatched_bank1': len(unmatched1),
        'unmatched_bank2': len(unmatched2),
        'match_rate': round(len(matched_pairs) / max(len(txns1), 1) * 100, 1),
    }

    run = _create_reconciliation_run(
    company_id=company_id,
    bank_account_1=acc1,
    bank_account_2=acc2,
    total_transactions=len(txns1) + len(txns2),
    matched_count=len(matched_pairs),
    receipt_missing_count=receipt_missing,
    unmatched_count=len(unmatched1) + len(unmatched2),
    match_percentage=stats["match_rate"],
)

    logger.info(f"Reconciliation complete: {stats}")
    return stats

def _create_reconciliation_run(
    company_id,
    bank_account_1,
    bank_account_2,
    matched_count,
    unmatched_count,
    receipt_missing_count,
    total_transactions,
    match_percentage,
):
    """
    Save reconciliation summary.
    """
    from banklist.models import ReconciliationRun

    return ReconciliationRun.objects.create(
        company_id=company_id,
        bank_account_1=bank_account_1,
        bank_account_2=bank_account_2,
        total_transactions=total_transactions,

        matched_count=matched_count,
        receipt_missing_count=receipt_missing_count,
        unmatched_count=unmatched_count,
        ignored_count=0,
        match_percentage=match_percentage,
    )


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
    ReceiptDocument.objects.filter(
        matched_transaction__isnull=False
    ).update(
        matched_transaction=None
    )


@db_transaction.atomic
def _save_results(matched_pairs, unmatched1, unmatched2):
    """Persist reconciliation results to DB."""
    from banklist.models import Transaction

    for txn1, txn2 in matched_pairs:
        txn1.reconcile_status = 'ignored'
        txn1.matched_txn = txn2
        txn1.save(update_fields=['reconcile_status','matched_txn'])

        txn2.reconcile_status = 'ignored'
        txn2.matched_txn = txn1
        txn2.save(update_fields=['reconcile_status','matched_txn'])

    for txn in unmatched1 + unmatched2:
        # txn.reconcile_status = 'unmatched'
        # txn.save(update_fields=['reconcile_status'])
        txn.matched_txn = None
        txn.reconcile_status = "unmatched"
        txn.save(update_fields=["matched_txn", "reconcile_status"])



def _match_receipts(company_id):
    """
    Match reconciled debit transactions with receipts.
    """

    from banklist.models import Transaction, ReceiptDocument

    receipt_missing = 0

    receipts = list(
        ReceiptDocument.objects.filter(
            company_id=company_id,
            extracted=True,
            matched_transaction__isnull=True,
        ).order_by("receipt_date", "id")
    )

    debit_transactions = (
        Transaction.objects.filter(
            company_id=company_id,
            txn_type="debit",
            # matched_txn__isnull=False,
        )
        .order_by("txn_date", "id")
    )

    for txn in debit_transactions:

        if txn.matched_txn:
            continue

        matched_receipt = None

        for receipt in receipts:

            if receipt.amount != txn.amount:
                continue

            if receipt.receipt_date:

                day_difference = abs(
                    (receipt.receipt_date - txn.txn_date).days
                )

                if day_difference > 1:
                    continue

            matched_receipt = receipt
            break

        if matched_receipt:

            matched_receipt.matched_transaction = txn
            matched_receipt.save(
                update_fields=["matched_transaction"]
            )

            receipts.remove(matched_receipt)

            txn.reconcile_status = "matched"

        else:

            txn.reconcile_status = "receipt_missing"

            receipt_missing += 1

        txn.save(update_fields=["reconcile_status"])

    return receipt_missing