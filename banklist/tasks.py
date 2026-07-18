# banklist/tasks.py

from celery import shared_task
from .services.google_drive_service import drive_service
import logging

logger = logging.getLogger(__name__)


# ============================================================
# DRIVE TASKS
# ============================================================

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def create_drive_folder_task(self, folder_name, company_name=None):
    return drive_service.create_bank_folder_structure(folder_name, company_name=company_name)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def upload_to_drive_task(self, file_bytes, file_name, folder_id, mime_type):
    class InMemoryFile:
        def __init__(self, data):
            self._data = data

        def read(self):
            return self._data

    return drive_service.upload_file(
        file_obj=InMemoryFile(file_bytes),
        file_name=file_name,
        folder_id=folder_id,
        mime_type=mime_type,
    )


# ============================================================
# STATEMENT PARSING TASK
# ============================================================

@shared_task(bind=True, max_retries=3)
def parse_statement_task(self, statement_id: int):
    """
    Parse an uploaded bank statement PDF (downloaded from Drive).
    Saves each transaction row to the Transaction table.

    FIX 1: balance=txn.balance is correct — ensure Transaction.balance
            is DecimalField(max_digits=15, decimal_places=2, null=True)
            so negative OD/CC balances like -24,86,368.47 are stored correctly.

    FIX 2: Duplicate check now cleans description before comparison
            so multiline narrations don't cause false mismatches.
    """
    from banklist.models import UploadedStatement, Transaction
    from banklist.services.pdf_parser import parse_bank_statement
    import re

    try:
        stmt = UploadedStatement.objects.select_related(
            'bank_account__company', 'bank_account__bank'
        ).get(id=statement_id)

        # Download file from Drive
        file_bytes = drive_service.download_file(stmt.drive_file_id)
        if not file_bytes:
            raise Exception(f"Could not download file from Drive: {stmt.drive_file_id}")

        # Parse PDF → list of ParsedTransaction
        result = parse_bank_statement(file_bytes, stmt.file_name)

        if result.errors and not result.transactions:
            stmt.parse_error = '; '.join(result.errors)
            stmt.parsed = False
            stmt.save(update_fields=['parse_error', 'parsed'])
            logger.error(f"Parse failed for statement {statement_id}: {result.errors}")
            return {'success': False, 'errors': result.errors}

        stmt.bank_detected = result.bank_name
        stmt.parsed = True
        stmt.save(update_fields=['bank_detected', 'parsed'])

        created = 0
        skipped = 0

        for txn in result.transactions:
            # ── FIX 2: clean description for duplicate check ──────────────
            # Raw descriptions from PDF contain \n and extra spaces.
            # Normalise before comparing so we don't miss real duplicates
            # or create false ones.
            clean_desc = ' '.join(txn.description.split())[:100]

            exists = Transaction.objects.filter(
                bank_account=stmt.bank_account,
                txn_date=txn.txn_date,
                amount=txn.amount,
                txn_type=txn.txn_type,
                description__startswith=clean_desc[:80],  # partial match is safer
            ).exists()

            if exists:
                skipped += 1
                continue

            # ── FIX 1: balance stored exactly as parsed ───────────────────
            # txn.balance from pdf_parser is already a Decimal, e.g.
            #   -2486368.47  (SBI OD account)
            #   25000.00     (regular savings)
            # Transaction.balance must be DecimalField(max_digits=15, decimal_places=2, null=True)
            Transaction.objects.create(
                bank_account=stmt.bank_account,
                statement=stmt,
                company=stmt.bank_account.company,
                txn_date=txn.txn_date,
                value_date=txn.value_date,
                description=clean_desc,
                ref_no=txn.ref_no or '',
                utr_no=txn.utr_no or '',
                txn_type=txn.txn_type,
                amount=txn.amount,
                balance=txn.balance,        # ← None if parser couldn't read it; negative is fine
                reconcile_status='unmatched',
            )
            created += 1

        logger.info(
            f"Statement {statement_id} ({result.bank_name}): "
            f"{created} created, {skipped} skipped duplicates"
        )
        return {
            'success': True,
            'bank': result.bank_name,
            'total_parsed': len(result.transactions),
            'created': created,
            'skipped': skipped,
        }

    except UploadedStatement.DoesNotExist:
        logger.error(f"Statement {statement_id} not found")
        return {'success': False, 'error': 'Statement not found'}

    except Exception as exc:
        logger.error(f"Task error for statement {statement_id}: {exc}", exc_info=True)
        self.retry(exc=exc, countdown=30)


# ============================================================
# RECEIPT PROCESSING TASKS
# ============================================================

@shared_task(bind=True, max_retries=3)
def process_receipt_task(self, receipt_id: int):
    """Download a receipt from Drive, extract amount/date, save to DB."""
    from banklist.models import ReceiptDocument
    from banklist.services.receipt_parser import parse_receipt_pdf

    try:
        receipt = ReceiptDocument.objects.get(id=receipt_id)
        logger.info(f"Processing receipt {receipt_id}: {receipt.file_name}")

        file_bytes = drive_service.download_file(receipt.drive_file_id)
        if not file_bytes:
            raise Exception(f"Could not download file from Drive: {receipt.drive_file_id}")

        result = parse_receipt_pdf(file_bytes, receipt.file_name)

        receipt.receipt_no   = result.get('receipt_no')   or receipt.receipt_no
        receipt.receipt_date = result.get('receipt_date') or receipt.receipt_date

        if result.get('amount'):
            receipt.amount           = result['amount']
            receipt.extracted        = True
            receipt.extraction_error = ''
            logger.info(f"Receipt {receipt_id}: ₹{receipt.amount}")
        else:
            receipt.extracted        = False
            receipt.extraction_error = result.get('error', 'Could not extract amount')
            logger.warning(f"Receipt {receipt_id}: {receipt.extraction_error}")

        receipt.save()

        return {
            'success':      True,
            'receipt_id':   receipt_id,
            'file_name':    receipt.file_name,
            'amount':       str(receipt.amount) if receipt.amount else None,
            'receipt_no':   receipt.receipt_no,
            'receipt_date': str(receipt.receipt_date) if receipt.receipt_date else None,
        }

    except ReceiptDocument.DoesNotExist:
        logger.error(f"Receipt {receipt_id} not found")
        return {'success': False, 'error': 'Receipt not found'}

    except Exception as exc:
        logger.error(f"Task error for receipt {receipt_id}: {exc}", exc_info=True)
        # FIX: don't pass max_retries inside retry() — it's set at task level
        self.retry(exc=exc, countdown=30)


@shared_task(bind=True, max_retries=3)
def process_all_receipts_task(self, company_id: int):
    """Queue processing for all unextracted receipts of a company."""
    from banklist.models import ReceiptDocument

    try:
        receipts = ReceiptDocument.objects.filter(
            company_id=company_id,
            extracted=False
        )

        if not receipts.exists():
            return {'success': True, 'message': 'No receipts to process', 'processed': 0}

        processed = 0
        failed    = 0
        results   = []

        for receipt in receipts:
            try:
                task = process_receipt_task.delay(receipt.id)
                results.append({
                    'receipt_id': receipt.id,
                    'file_name':  receipt.file_name,
                    'task_id':    task.id,
                    'status':     'queued',
                })
                processed += 1
            except Exception as e:
                logger.error(f"Failed to queue receipt {receipt.id}: {e}")
                failed += 1
                results.append({
                    'receipt_id': receipt.id,
                    'file_name':  receipt.file_name,
                    'status':     'failed',
                    'error':      str(e),
                })

        return {
            'success':      True,
            'company_id':   company_id,
            'total_queued': processed,
            'failed':       failed,
            'results':      results,
        }

    except Exception as exc:
        logger.error(f"Task error for company {company_id}: {exc}", exc_info=True)
        self.retry(exc=exc, countdown=30)


# ============================================================
# RECONCILIATION TASK
# ============================================================

@shared_task(bind=True, max_retries=3)
def run_reconciliation_task(self, company_id: int, bank_account_1_id: int = None,
                            bank_account_2_id: int = None, date_from: str = None,
                            date_to: str = None, auto_match: bool = True):
    """Run full reconciliation asynchronously."""
    from banklist.models import Company
    from banklist.services.enhanced_reconciliation_engine import run_full_reconciliation

    try:
        company = Company.objects.get(id=company_id)
        logger.info(f"Running reconciliation for company {company_id}")

        result = run_full_reconciliation(
            company=company,
            bank_account_1_id=bank_account_1_id,
            bank_account_2_id=bank_account_2_id,
            date_from=date_from,
            date_to=date_to,
            auto_match=auto_match,
        )

        logger.info(f"Reconciliation complete for company {company_id}: {result['summary']}")
        return {
            'success':          True,
            'company_id':       company_id,
            'run_id':           result['run_id'],
            'summary':          result['summary'],
            'run_time_seconds': result['run_time_seconds'],
        }

    except Company.DoesNotExist:
        logger.error(f"Company {company_id} not found")
        return {'success': False, 'error': 'Company not found'}

    except Exception as exc:
        logger.error(f"Task error for company {company_id}: {exc}", exc_info=True)
        self.retry(exc=exc, countdown=30)


# ============================================================
# MAINTENANCE TASKS
# ============================================================

@shared_task(bind=True, max_retries=3)
def cleanup_audit_logs_task(self, days_to_keep: int = 30):
    """Delete audit logs older than N days."""
    from banklist.models import AuditLog
    from django.utils import timezone
    from datetime import timedelta

    try:
        cutoff = timezone.now() - timedelta(days=days_to_keep)
        count  = AuditLog.objects.filter(timestamp__lt=cutoff).count()
        AuditLog.objects.filter(timestamp__lt=cutoff).delete()
        logger.info(f"Deleted {count} audit logs older than {days_to_keep} days")
        return {'success': True, 'deleted_count': count, 'days_kept': days_to_keep}
    except Exception as exc:
        logger.error(f"Cleanup task error: {exc}", exc_info=True)
        self.retry(exc=exc, countdown=60)


@shared_task(bind=True, max_retries=3)
def retry_failed_receipts_task(self, company_id: int = None):
    """Retry all receipts where extracted=False."""
    from banklist.models import ReceiptDocument
    from banklist.services.receipt_parser import parse_receipt_pdf

    try:
        receipts = ReceiptDocument.objects.filter(extracted=False)
        if company_id:
            receipts = receipts.filter(company_id=company_id)

        if not receipts.exists():
            return {'success': True, 'message': 'No failed receipts', 'processed': 0}

        processed  = 0
        successful = 0
        failed     = 0

        for receipt in receipts:
            processed += 1
            try:
                file_bytes = drive_service.download_file(receipt.drive_file_id)
                if not file_bytes:
                    receipt.extraction_error = 'Failed to download from Drive'
                    receipt.save(update_fields=['extraction_error'])
                    failed += 1
                    continue

                result = parse_receipt_pdf(file_bytes, receipt.file_name)

                if result.get('amount'):
                    receipt.amount           = result['amount']
                    receipt.receipt_no       = result.get('receipt_no')   or receipt.receipt_no
                    receipt.receipt_date     = result.get('receipt_date') or receipt.receipt_date
                    receipt.extracted        = True
                    receipt.extraction_error = ''
                    receipt.save()
                    successful += 1
                    logger.info(f"Retried receipt {receipt.id}: ₹{receipt.amount}")
                else:
                    receipt.extraction_error = result.get('error', 'Could not extract amount')
                    receipt.save(update_fields=['extraction_error'])
                    failed += 1

            except Exception as e:
                receipt.extraction_error = str(e)
                receipt.save(update_fields=['extraction_error'])
                failed += 1
                logger.error(f"Failed to retry receipt {receipt.id}: {e}")

        return {
            'success':    True,
            'processed':  processed,
            'successful': successful,
            'failed':     failed,
        }

    except Exception as exc:
        logger.error(f"Retry failed receipts error: {exc}", exc_info=True)
        self.retry(exc=exc, countdown=30)


@shared_task(bind=True, max_retries=1)
def check_failed_tasks_task(self):
    """Placeholder — check for failed Celery tasks."""
    try:
        logger.info("Checking for failed tasks...")
        return {'success': True, 'message': 'Failed tasks check completed'}
    except Exception as exc:
        logger.error(f"Check failed tasks error: {exc}")
        return {'success': False, 'error': str(exc)}
