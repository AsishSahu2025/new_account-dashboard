import logging
import time

from django.db import transaction

from banklist.models import (
    Transaction,
    ReceiptDocument,
    ReconciliationRun,
    ReconciliationRule,
    BankAccount,
)

from banklist.services.reconciliation_engine import run_reconciliation

logger = logging.getLogger(__name__)


class ReconciliationV2Engine:

    def __init__(self, company, user=None):
        self.company = company
        self.user = user
        # Load active reconciliation rules for the company.
        # If none exist, create a default rule.
        self.rules, _ = ReconciliationRule.objects.get_or_create(
            company=company,
            defaults={
                "name": "Default Rule",
                "is_active": True,
                "match_by_amount": True,
                "amount_tolerance": 0,
                "match_by_date": True,
                "date_tolerance_days": 1,
                "match_by_utr": False,
            },
        )

        # If multiple rules exist, prefer the active one.
        active_rule = (
            ReconciliationRule.objects.filter(
                company=company,
                is_active=True,
            )
            .order_by("-id")
            .first()
        )

        if active_rule:
            self.rules = active_rule

        logger.info(
            "Using Reconciliation Rule: %s",
            self.rules.name,
        )

    @transaction.atomic
    def run(
        self,
        bank_account_1_id,
        bank_account_2_id,
        date_from=None,
        date_to=None,
        auto_match=True,
    ):
        """
        Execute the complete reconciliation process.
        """

        start = time.time()

        logger.info("Starting Reconciliation V2...")

        bank_result = self._run_bank_reconciliation(
            bank_account_1_id,
            bank_account_2_id,
            date_from,
            date_to,
        )

        receipt_result = self._run_receipt_matching(
            bank_account_1_id,
            bank_account_2_id,
            date_from,
            date_to,
        )

        summary = self._get_combined_statistics(
            bank_account_1_id,
            bank_account_2_id,
            date_from,
            date_to,
        )

        run = self._create_reconciliation_run(
            bank_account_1_id,
            bank_account_2_id,
            summary,
            auto_match,
            time.time() - start,
        )

        logger.info("Reconciliation V2 completed successfully.")

        return {
            "success": True,
            "run_id": run.id,
            "bank_reconciliation": bank_result,
            "receipt_matching": receipt_result,
            "summary": summary,
            "run_time_seconds": round(time.time() - start, 2),
        }

    def _run_bank_reconciliation(
    self,
    bank_account_1_id,
    bank_account_2_id,
    date_from=None,
    date_to=None):

        logger.info(
            "Running bank reconciliation | Bank1=%s | Bank2=%s",
            bank_account_1_id,
            bank_account_2_id,
        )

        result = run_reconciliation(
            bank_account_1_id=bank_account_1_id,
            bank_account_2_id=bank_account_2_id,
            company_id=self.company.id,
            date_from=date_from,
            date_to=date_to,
        )

        if not result:
            raise Exception("Bank reconciliation returned no response.")

        if isinstance(result, dict) and result.get("error"):
            raise Exception(result["error"])

        logger.info(
            "Bank reconciliation finished successfully. Matched=%s Unmatched1=%s Unmatched2=%s",
            result.get("matched_count", 0),
            result.get("unmatched_bank1", 0),
            result.get("unmatched_bank2", 0),
        )



        return result


    def _run_receipt_matching(
    self,
    bank_account_1_id,
    bank_account_2_id,
    date_from=None,
    date_to=None,
):
        """
        Match bank transactions with uploaded receipts.

        This method does NOT perform bank-to-bank reconciliation.
        It only links eligible transactions with extracted receipts.
        """

        logger.info("Starting receipt matching...")

        transactions = self._get_transactions_for_receipt_matching(
            bank_account_1_id,
            bank_account_2_id,
            date_from,
            date_to,
        )

        receipts = list(
            ReceiptDocument.objects.filter(
                company=self.company,
                extracted=True,
                matched_transaction__isnull=True,
            ).order_by("receipt_date", "id")
        )

        if not receipts:
            logger.info("No extracted receipts found.")

            return {
                "matched": 0,
                "receipt_missing": 0,
                "total_processed": 0,
                "total_receipts": 0,
                "message": "No extracted receipts found.",
            }

        matched_count = 0
        receipt_missing_count = 0
        processed_count = 0

        for transaction in transactions:

            # Future proof
            if not self._should_have_receipt(transaction):
                continue

            processed_count += 1

            matched_receipt = self._find_matching_receipt(
                transaction,
                receipts,
            )

            if matched_receipt:

                matched_receipt.matched_transaction = transaction
                matched_receipt.save(
                    update_fields=["matched_transaction"]
                )

                transaction.reconcile_status = "matched"
                transaction.save(
                    update_fields=["reconcile_status"]
                )

                receipts.remove(matched_receipt)

                matched_count += 1

                logger.info(
                    "Receipt %s matched with Transaction %s",
                    matched_receipt.id,
                    transaction.id,
                )

            else:

                transaction.reconcile_status = "receipt_missing"
                transaction.save(
                    update_fields=["reconcile_status"]
                )

                receipt_missing_count += 1

                logger.info(
                    "Receipt missing for Transaction %s",
                    transaction.id,
                )

        logger.info(
            "Receipt Matching Completed | Matched=%s Missing=%s",
            matched_count,
            receipt_missing_count,
        )

        return {
            "matched": matched_count,
            "receipt_missing": receipt_missing_count,
            "total_processed": processed_count,
            "total_receipts": len(receipts) + matched_count,
        }


    def _find_matching_receipt(self, transaction, receipts):
        """
        Find the best matching receipt for a transaction.

        Priority:
            1. Amount
            2. Date (within configured tolerance)
            3. UTR/Receipt No (future support)

        Returns:
            ReceiptDocument | None
        """

        best_match = None
        best_score = -1

        for receipt in receipts:

            score = 0

            # ----------------------------------
            # Amount Match (Mandatory)
            # ----------------------------------
            if self.rules.match_by_amount:

                amount_diff = abs(
                    float(receipt.amount) - float(transaction.amount)
                )

                if amount_diff <= float(self.rules.amount_tolerance):
                    score += 100
                else:
                    continue

            # ----------------------------------
            # Date Match
            # ----------------------------------
            if (
                self.rules.match_by_date
                and receipt.receipt_date
            ):

                date_diff = abs(
                    (receipt.receipt_date - transaction.txn_date).days
                )

                if date_diff <= self.rules.date_tolerance_days:
                    score += 20
                else:
                    continue

            # ----------------------------------
            # UTR / Receipt Number
            # (Future Support)
            # ----------------------------------
            if (
                self.rules.match_by_utr
                and transaction.utr_no
                and receipt.receipt_no
            ):

                if (
                    transaction.utr_no.strip()
                    == receipt.receipt_no.strip()
                ):
                    score += 50

            # ----------------------------------
            # Keep Best Match
            # ----------------------------------
            if score > best_score:
                best_score = score
                best_match = receipt

        if best_match:

            logger.info(
                "Matched Transaction %s -> Receipt %s (Score=%s)",
                transaction.id,
                best_match.id,
                best_score,
            )

        return best_match


    def _should_have_receipt(self, transaction):
        """
        Determine whether a transaction should be matched with a receipt.

        Current Rule:
            - Only debit transactions require receipts.

        Future:
            - Credit transactions can also be enabled without
            changing the receipt matching engine.
        """

        # Ignore transactions already paired during bank reconciliation
        if transaction.matched_txn:
            return False

        # Ignore transactions without amount
        if not transaction.amount:
            return False

        # Current business rule
        if transaction.txn_type.lower() == "debit":
            return True

        # Future enhancement:
        # if transaction.txn_type.lower() == "credit":
        #     return True

        return False


    def _get_transactions_for_receipt_matching(
    self,
    bank_account_1_id=None,
    bank_account_2_id=None,
    date_from=None,
    date_to=None,
):
        """
        Fetch transactions eligible for receipt matching.

        Current Business Rules:
        - Only transactions belonging to the current company.
        - Exclude internal transfer matches (matched_txn).
        - Receipt eligibility is determined later by
        _should_have_receipt().
        """

        queryset = Transaction.objects.filter(
            company=self.company,
            txn_type="debit"
        )

        # Filter by selected bank accounts
        bank_accounts = [
            account_id
            for account_id in [bank_account_1_id, bank_account_2_id]
            if account_id
        ]

        if bank_accounts:
            queryset = queryset.filter(
                bank_account_id__in=bank_accounts
            )

        # Filter by date range
        if date_from:
            queryset = queryset.filter(
                txn_date__gte=date_from
            )

        if date_to:
            queryset = queryset.filter(
                txn_date__lte=date_to
            )

        # Ignore transactions already paired with another
        # bank transaction (internal transfer)
        queryset = queryset.filter(
            matched_txn__isnull=True
        )

        queryset = queryset.order_by(
            "txn_date",
            "id",
        )

        logger.info(
            "Found %s transactions for receipt matching.",
            queryset.count(),
        )

        return queryset



    def _get_combined_statistics(
    self,
    bank_account_1_id=None,
    bank_account_2_id=None,
    date_from=None,
    date_to=None,
):
        """
        Generate overall reconciliation statistics.
        """

        queryset = Transaction.objects.filter(
            company=self.company
        )

        # Filter by selected bank accounts
        bank_accounts = [
            account_id
            for account_id in [bank_account_1_id, bank_account_2_id]
            if account_id
        ]

        if bank_accounts:
            queryset = queryset.filter(
                bank_account_id__in=bank_accounts
            )

        # Date filters
        if date_from:
            queryset = queryset.filter(txn_date__gte=date_from)

        if date_to:
            queryset = queryset.filter(txn_date__lte=date_to)

        total_transactions = queryset.count()

        matched_transactions = queryset.filter(
            reconcile_status="matched"
        ).count()

        receipt_missing = queryset.filter(
            reconcile_status="receipt_missing"
        ).count()

        ignored_transactions = queryset.filter(
            reconcile_status="ignored"
        ).count()

        unmatched_transactions = queryset.filter(
            reconcile_status="unmatched"
        ).count()

        summary = {
            "total_transactions": total_transactions,
            "matched_transactions": matched_transactions,
            "receipt_missing": receipt_missing,
            "ignored_transactions": ignored_transactions,
            "unmatched_transactions": unmatched_transactions,
            "reconciliation_percentage": (
                round(
                    (matched_transactions / total_transactions) * 100,
                    2,
                )
                if total_transactions
                else 0
            ),
        }

        logger.info("Reconciliation Summary: %s", summary)

        return summary



    def _create_reconciliation_run(
    self,
    bank_account_1_id,
    bank_account_2_id,
    summary,
    auto_match,
    run_time_seconds,
):
        """
        Save the reconciliation run for audit/history.
        """

        run = ReconciliationRun.objects.create(
            company=self.company,
            bank_account_1_id=bank_account_1_id,
            bank_account_2_id=bank_account_2_id,
            total_transactions=summary["total_transactions"],
            matched_count=summary["matched_transactions"],
            receipt_missing_count=summary["receipt_missing"],
            unmatched_count=summary["unmatched_transactions"],
            ignored_count=summary["ignored_transactions"],
            match_percentage=summary["reconciliation_percentage"],
            run_time_seconds=round(run_time_seconds, 2),
            is_auto=auto_match,
            run_by=self.user,
        )

        logger.info(
            "Reconciliation run %s created successfully.",
            run.id,
        )

        return run

    @transaction.atomic
    def auto_receipt_matching(self, receipt):

        logger.info(
            "Starting Auto Receipt Matching for Receipt %s",
            receipt.id,
        )

        if not receipt.extracted:
            logger.info("Receipt is not extracted yet.")
            return {
                "success": False,
                "message": "Receipt is not extracted yet."
            }

        if receipt.matched_transaction:
            logger.info("Receipt already matched.")
            return {
                "success": True,
                "message": "Receipt already matched."
            }

        transactions = self._get_transactions_for_receipt_matching(
            bank_account_1_id=None,
            bank_account_2_id=None,
            date_from=None,
            date_to=None,
        )

        matched = 0

        #
        # IMPORTANT:
        # Reuse the existing matching logic.
        #
        matched_transaction = None

        for transaction in transactions:

            if not self._should_have_receipt(transaction):
                continue

            receipt_match = self._find_matching_receipt(
                transaction,
                [receipt],
            )

            if receipt_match:

                matched_transaction = transaction
                break

        if matched_transaction:

            receipt.matched_transaction = matched_transaction
            receipt.save(
                update_fields=[
                    "matched_transaction",
                ]
            )

            matched_transaction.reconcile_status = "matched"
            matched_transaction.save(
                update_fields=[
                    "reconcile_status",
                ]
            )

            logger.info(
                "Receipt %s matched with Transaction %s",
                receipt.id,
                matched_transaction.id,
            )

            matched = 1

        return {
            "success": True,
            "matched": matched,
        }

    @transaction.atomic
    def auto_bank_reconciliation(self, uploaded_bank_account_id):

        logger.info(
            "Starting Auto Bank Reconciliation for Bank %s",
            uploaded_bank_account_id,
        )

        other_accounts = BankAccount.objects.filter(
            company=self.company
        ).exclude(
            id=uploaded_bank_account_id
        )

        if not other_accounts.exists():

            logger.info(
                "No other bank accounts found for reconciliation."
            )

            return {
                "success": True,
                "matched_banks": 0,
                "results": [],
            }

        results = []

        for account in other_accounts:

            logger.info(
                "Reconciling Bank %s <-> Bank %s",
                uploaded_bank_account_id,
                account.id,
            )

            result = self._run_bank_reconciliation(
                bank_account_1_id=uploaded_bank_account_id,
                bank_account_2_id=account.id,
            )

            results.append({
                "bank_account_id": account.id,
                "result": result,
            })

        logger.info(
            "Auto Bank Reconciliation completed."
        )

        return {
            "success": True,
            "matched_banks": len(results),
            "results": results,
        }



def run_reconciliation_v2(
    company,
    user=None,
    bank_account_1_id=None,
    bank_account_2_id=None,
    date_from=None,
    date_to=None,
    auto_match=True,
):
    engine = ReconciliationV2Engine(company, user)

    return engine.run(
        bank_account_1_id=bank_account_1_id,
        bank_account_2_id=bank_account_2_id,
        date_from=date_from,
        date_to=date_to,
        auto_match=auto_match,
    )


def auto_receipt_matching(company, receipt):

    engine = ReconciliationV2Engine(
        company=company,
        user=None,
    )

    return engine.auto_receipt_matching(receipt)


def auto_bank_reconciliation(
    company,
    uploaded_bank_account_id,
):

    engine = ReconciliationV2Engine(
        company=company,
        user=None,
    )

    return engine.auto_bank_reconciliation(
        uploaded_bank_account_id
    )