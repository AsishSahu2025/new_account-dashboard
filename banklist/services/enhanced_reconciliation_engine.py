"""
Enhanced Reconciliation Engine - Integrates bank-to-bank matching with receipt matching
"""

import logging
import time
from decimal import Decimal
from django.db.models import Q

from ..models import (
    Transaction, ReceiptDocument, ReconciliationRun, 
    ReconciliationRule, BankAccount
)

logger = logging.getLogger(__name__)


class EnhancedReconciliationEngine:
    """Handles both bank-to-bank and receipt matching"""
    
    def __init__(self, company, user=None):
        self.company = company
        self.user = user
        self.rules = self._get_or_create_rules()
    
    def _get_or_create_rules(self):
        """Get reconciliation rules or create defaults"""
        try:
            return ReconciliationRule.objects.get(company=self.company, is_active=True)
        except ReconciliationRule.DoesNotExist:
            return ReconciliationRule.objects.create(
                company=self.company,
                name='Default Rules',
                is_active=True,
                match_by_amount=True,
                amount_tolerance=0.01,
                match_by_date=True,
                date_tolerance_days=3,
                match_by_utr=True,
                require_receipt_above_amount=1000
            )
    
    def run_full_reconciliation(self, bank_account_1_id: int, bank_account_2_id: int,
                                date_from=None, date_to=None, auto_match=True) -> dict:
        """Run full reconciliation including bank-to-bank and receipt matching"""
        start_time = time.time()
        
        # Step 1: Bank-to-bank reconciliation using existing engine
        bank_stats = self._run_bank_reconciliation(
            bank_account_1_id, bank_account_2_id, date_from, date_to
        )
        
        # Step 2: Receipt matching for both accounts
        receipt_stats = self._run_receipt_matching(
            bank_account_1_id, bank_account_2_id, date_from, date_to
        )
        
        # Step 3: Get combined statistics
        combined_stats = self._get_combined_stats(
            bank_account_1_id, bank_account_2_id, date_from, date_to
        )
        
        # Step 4: Create reconciliation run record
        run_time = time.time() - start_time
        run_record = self._create_run_record(
            bank_account_1_id, bank_account_2_id, combined_stats, run_time, auto_match
        )
        
        return {
            'run_id': run_record.id,
            'bank_reconciliation': bank_stats,
            'receipt_matching': receipt_stats,
            'summary': combined_stats,
            'run_time_seconds': round(run_time, 2)
        }
    
    def _run_bank_reconciliation(self, bank_account_1_id, bank_account_2_id, date_from, date_to):
        """Run bank-to-bank reconciliation using existing engine"""
        from .reconciliation_engine import run_reconciliation
        
        result = run_reconciliation(
            bank_account_1_id=bank_account_1_id,
            bank_account_2_id=bank_account_2_id,
            company_id=self.company.id,
            date_from=date_from,
            date_to=date_to
        )
        
        if 'error' in result:
            raise Exception(result['error'])
        
        return result
    
    def _run_receipt_matching(self, bank_account_1_id, bank_account_2_id, date_from, date_to):
        """Match transactions with receipts"""
        # Get transactions from both accounts
        transactions = self._get_transactions_for_receipt_matching(
            bank_account_1_id, bank_account_2_id, date_from, date_to
        )
        
        # Get all extracted receipts
        receipts = ReceiptDocument.objects.filter(
            company=self.company,
            extracted=True,
            amount__isnull=False,
            receipt_date__isnull=False
        )
        
        if not receipts.exists():
            return {
                'matched': 0,
                'receipt_missing': 0,
                'total_processed': 0,
                'total_receipts': 0,
                'message': 'No extracted receipts found'
            }
        
        matched_count = 0
        receipt_missing_count = 0
        processed_count = 0
        
        for transaction in transactions:
            # Skip if already matched in bank reconciliation
            if transaction.reconcile_status == 'matched':
                continue
            
            # Check if transaction should have a receipt
            should_have_receipt = self._should_have_receipt(transaction)
            
            if not should_have_receipt:
                continue
            
            processed_count += 1
            
            # Try to find matching receipt
            best_match, match_score = self._find_matching_receipt(transaction, receipts)
            
            if best_match:
                transaction.reconcile_status = 'matched'
                transaction.save(update_fields=['reconcile_status'])
                matched_count += 1
                logger.info(f"Receipt matched: Transaction {transaction.id} -> Receipt {best_match.id}")
            else:
                transaction.reconcile_status = 'receipt_missing'
                transaction.save(update_fields=['reconcile_status'])
                receipt_missing_count += 1
        
        return {
            'matched': matched_count,
            'receipt_missing': receipt_missing_count,
            'total_processed': processed_count,
            'total_receipts': receipts.count()
        }
    
    def _find_matching_receipt(self, transaction, receipts):
        """Find matching receipt using multiple criteria"""
        best_match = None
        best_score = 0
        
        for receipt in receipts:
            score = 0
            total_checks = 0
            
            # 1. Amount match
            if self.rules.match_by_amount:
                total_checks += 1
                amount_diff = abs(float(receipt.amount) - float(transaction.amount))
                if amount_diff <= float(self.rules.amount_tolerance):
                    score += 1
                elif amount_diff <= float(self.rules.amount_tolerance) * 10:
                    score += 0.5
            
            # 2. Date match
            if self.rules.match_by_date and receipt.receipt_date:
                total_checks += 1
                date_diff = abs((receipt.receipt_date - transaction.txn_date).days)
                if date_diff <= self.rules.date_tolerance_days:
                    score += 1
                elif date_diff <= self.rules.date_tolerance_days * 2:
                    score += 0.5
            
            # 3. UTR/Reference number match
            if self.rules.match_by_utr and transaction.utr_no and receipt.receipt_no:
                total_checks += 1
                if transaction.utr_no.strip() == receipt.receipt_no.strip():
                    score += 1
            
            # Calculate match percentage
            if total_checks > 0:
                match_score = (score / total_checks) * 100
                if match_score > best_score and match_score >= 60:
                    best_score = match_score
                    best_match = receipt
        
        return best_match, best_score
    
    def _should_have_receipt(self, transaction):
        """Determine if a transaction should have a receipt"""
        if self.rules.require_receipt_above_amount:
            if transaction.amount >= self.rules.require_receipt_above_amount:
                return True
        
        if transaction.txn_type == 'credit' and transaction.amount >= 500:
            return True
        
        if transaction.txn_type == 'debit' and transaction.amount >= 10000:
            return True
        
        return False
    
    def _get_transactions_for_receipt_matching(self, bank_account_1_id, bank_account_2_id, date_from, date_to):
        """Get transactions for receipt matching"""
        qs = Transaction.objects.filter(
            company=self.company,
            reconcile_status__in=['unmatched', 'receipt_missing']
        )
        
        if bank_account_1_id:
            qs = qs.filter(bank_account_id=bank_account_1_id)
        if bank_account_2_id:
            qs = qs.filter(bank_account_id=bank_account_2_id)
        
        if date_from:
            qs = qs.filter(txn_date__gte=date_from)
        if date_to:
            qs = qs.filter(txn_date__lte=date_to)
        
        return qs
    
    def _get_combined_stats(self, bank_account_1_id, bank_account_2_id, date_from, date_to):
        """Get combined reconciliation statistics"""
        qs = Transaction.objects.filter(company=self.company)
        
        if bank_account_1_id:
            qs = qs.filter(bank_account_id=bank_account_1_id)
        if bank_account_2_id:
            qs = qs.filter(bank_account_id=bank_account_2_id)
        
        if date_from:
            qs = qs.filter(txn_date__gte=date_from)
        if date_to:
            qs = qs.filter(txn_date__lte=date_to)
        
        total = qs.count()
        matched = qs.filter(reconcile_status='matched').count()
        receipt_missing = qs.filter(reconcile_status='receipt_missing').count()
        unmatched = qs.filter(reconcile_status='unmatched').count()
        ignored = qs.filter(reconcile_status='ignored').count()
        
        match_percentage = (matched / total * 100) if total > 0 else 0
        
        return {
            'total': total,
            'matched': matched,
            'receipt_missing': receipt_missing,
            'unmatched': unmatched,
            'ignored': ignored,
            'match_percentage': round(match_percentage, 2)
        }
    
    def _create_run_record(self, bank_account_1_id, bank_account_2_id, stats, run_time, auto_match):
        """Create reconciliation run record"""
        return ReconciliationRun.objects.create(
            company=self.company,
            bank_account_1_id=bank_account_1_id,
            bank_account_2_id=bank_account_2_id,
            total_transactions=stats['total'],
            matched_count=stats['matched'],
            receipt_missing_count=stats['receipt_missing'],
            unmatched_count=stats['unmatched'],
            ignored_count=stats['ignored'],
            match_percentage=stats['match_percentage'],
            run_time_seconds=run_time,
            is_auto=auto_match,
            run_by=self.user
        )


# Public API functions
def run_full_reconciliation(company, user=None, bank_account_1_id=None, 
                           bank_account_2_id=None, date_from=None, 
                           date_to=None, auto_match=True):
    """Run full reconciliation with both bank and receipt matching"""
    engine = EnhancedReconciliationEngine(company, user)
    return engine.run_full_reconciliation(
        bank_account_1_id, bank_account_2_id, date_from, date_to, auto_match
    )


def match_with_receipts_only(company, bank_account_id=None, user=None):
    """Match transactions with receipts only (no bank-to-bank)"""
    engine = EnhancedReconciliationEngine(company, user)
    return engine._run_receipt_matching(
        bank_account_id, None, None, None
    )