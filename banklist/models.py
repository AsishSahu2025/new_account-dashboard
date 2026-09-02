from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone


# Create your models here.


class Bank(models.Model):
    bank_name = models.CharField(max_length=255)
    short_name = models.CharField(max_length=50, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)



    
    def __str__(self):
        return self.bank_name
    
    class Meta:
        db_table = 'banks'
        ordering = ['bank_name']


class Company(models.Model):
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'companies'


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email is required')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    email       = models.EmailField(unique=True)
    full_name   = models.CharField(max_length=255)
    company     = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, blank=True)
    is_active   = models.BooleanField(default=True)
    is_staff    = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD  = 'email'
    REQUIRED_FIELDS = ['full_name']

    objects = UserManager()

    def __str__(self):
        return self.email

    class Meta:
        db_table = 'users'
        app_label = 'banklist'


class BankAccount(models.Model):
    """Stores a bank account created by a user/company, linked to Google Drive folders."""
    company       = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='bank_accounts')
    bank          = models.ForeignKey(Bank, on_delete=models.CASCADE)
    account_holder_name = models.CharField(max_length=255)
    account_number      = models.CharField(max_length=100)
    ifsc_code           = models.CharField(max_length=20, blank=True, null=True)
    bank_folder_id      = models.CharField(max_length=255, blank=True, null=True)
    statement_folder_id = models.CharField(max_length=255, blank=True, null=True)
    drive_link          = models.URLField(max_length=500, blank=True, null=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.bank.bank_name} - {self.account_holder_name} - {self.account_number}"

    class Meta:
        db_table = 'bank_accounts'
        ordering = ['-created_at']
        unique_together = ['company', 'account_number', 'bank']



class UploadedStatement(models.Model):
    """Tracks each PDF file uploaded per bank account."""
    bank_account   = models.ForeignKey('BankAccount', on_delete=models.CASCADE,
                                       related_name='statements')
    file_name      = models.CharField(max_length=255)
    drive_file_id  = models.CharField(max_length=255, blank=True)
    bank_detected  = models.CharField(max_length=50, blank=True)   # SBI / DBS / HDFC
    parsed         = models.BooleanField(default=False)
    parse_error    = models.TextField(blank=True)
    uploaded_at    = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        db_table = 'uploaded_statements'
 
    def __str__(self):
        return f"{self.file_name} ({self.bank_account})"


class Particular(models.Model):
    name = models.CharField(max_length=200, unique=True)
    is_active = models.BooleanField(default=True)
    transaction_type = models.CharField(
    max_length=10,
    choices=[
        ("debit", "Debit"),
        ("credit", "Credit"),
    ],
)
    created_at = models.DateTimeField(auto_now_add=True)



class AccountingParticular(models.Model):
    name = models.CharField(max_length=100,unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounting_particular"
        ordering = ["name"]

    def __str__(self):
        return self.name

 
class Transaction(models.Model):
    """One row from a parsed bank statement."""
 
    TRANSACTION_TYPE = [
        ('debit',  'Debit'),
        ('credit', 'Credit'),
    ]
 
    bank_account  = models.ForeignKey('BankAccount', on_delete=models.CASCADE,
                                      related_name='transactions')
    statement     = models.ForeignKey(UploadedStatement, on_delete=models.SET_NULL,
                                      null=True, related_name='transactions')
 
    txn_date      = models.DateField()
    value_date    = models.DateField(null=True, blank=True)
    description   = models.TextField()
    ref_no        = models.CharField(max_length=255, blank=True)   # UTR / Cheque
    utr_no        = models.CharField(max_length=100, blank=True)   # extracted UTR
 
    txn_type      = models.CharField(max_length=10, choices=TRANSACTION_TYPE)
    amount        = models.DecimalField(max_digits=15, decimal_places=2)
    balance       = models.DecimalField(max_digits=15, decimal_places=2, null=True,blank=True)
 
    # Reconciliation fields (filled later)
    reconcile_status = models.CharField(max_length=30, default='unmatched',
        choices=[
            ('matched',         'Matched'),
            ('unmatched',       'Unmatched'),
            ('receipt_missing', 'Receipt Missing'),
            ('ignored',         'Ignored'),
        ]
    )
    matched_txn   = models.ForeignKey('self', null=True, blank=True,
                                      on_delete=models.SET_NULL,
                                      related_name='matched_by')
    company       = models.ForeignKey('Company', on_delete=models.CASCADE,
                                      related_name='transactions')
    created_at    = models.DateTimeField(auto_now_add=True)
    particular = models.ForeignKey(Particular, null=True, blank=True, on_delete=models.SET_NULL)
    accounting_particular = models.ForeignKey(AccountingParticular, null=True, blank=True, on_delete=models.SET_NULL)
 
    class Meta:
        db_table = 'transactions'
        ordering = ['txn_date']
        indexes = [
            models.Index(fields=['bank_account', 'txn_date']),
            models.Index(fields=['utr_no']),
            models.Index(fields=['reconcile_status']),
        ]
 
    def __str__(self):
        # return f"{self.txn_date} | {self.txn_type} ₹{self.amount} | {self.description[:40]}"
        return f"{self.id} | {self.bank_account}"


class ReceiptDocument(models.Model):
    """Tracks receipt files stored in Drive Billing_Receipt folder."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='receipts')
    matched_transaction = models.ForeignKey(
    "Transaction",
    null=True,
    blank=True,
    on_delete=models.SET_NULL,
    related_name="matched_receipts",
)
    drive_file_id = models.CharField(max_length=255)
    file_name = models.CharField(max_length=255)
    file_link = models.URLField(max_length=500, blank=True, null=True)
    mime_type = models.CharField(max_length=150, blank=True)
    extracted = models.BooleanField(default=False)
    extraction_error = models.TextField(blank=True)
    receipt_no = models.CharField(max_length=120, blank=True)
    receipt_date = models.DateField(null=True, blank=True)
    amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    uploaded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'receipt_documents'
        ordering = ['-uploaded_at', '-created_at']
        unique_together = ['company', 'drive_file_id']
        indexes = [
            models.Index(fields=['company', 'extracted']),
            models.Index(fields=['receipt_date']),
        ]

    def __str__(self):
        return f"{self.file_name} ({self.company})"


# ============================================================
# RECONCILIATION MODELS
# ============================================================

class ReconciliationRun(models.Model):
    """Track each reconciliation run for audit purposes"""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='reconciliation_runs')
    bank_account_1 = models.ForeignKey('BankAccount', on_delete=models.CASCADE, 
                                        null=True, blank=True, related_name='reconciliation_runs_as_first')
    bank_account_2 = models.ForeignKey('BankAccount', on_delete=models.CASCADE, 
                                        null=True, blank=True, related_name='reconciliation_runs_as_second')
    run_date = models.DateTimeField(auto_now_add=True)
    
    total_transactions = models.IntegerField(default=0)
    matched_count = models.IntegerField(default=0)
    receipt_missing_count = models.IntegerField(default=0)
    unmatched_count = models.IntegerField(default=0)
    ignored_count = models.IntegerField(default=0)
    match_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    run_time_seconds = models.FloatField(default=0)
    is_auto = models.BooleanField(default=False)
    run_by = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, related_name='reconciliation_runs')
    
    class Meta:
        db_table = 'reconciliation_runs'
        ordering = ['-run_date']
    
    def __str__(self):
        return f"Reconciliation {self.run_date} - {self.company.name}"


class ReconciliationRule(models.Model):
    """Custom rules for matching transactions"""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='reconciliation_rules')
    name = models.CharField(max_length=255, default='Default Rules')
    is_active = models.BooleanField(default=True)
    
    # Matching rules
    match_by_amount = models.BooleanField(default=True)
    amount_tolerance = models.DecimalField(max_digits=5, decimal_places=2, default=0.01)
    match_by_date = models.BooleanField(default=True)
    date_tolerance_days = models.IntegerField(default=3)
    match_by_utr = models.BooleanField(default=True)
    match_by_description = models.BooleanField(default=False)
    description_similarity_threshold = models.FloatField(default=0.8)
    
    # Auto-match settings
    auto_match_on_upload = models.BooleanField(default=False)
    require_receipt_above_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'reconciliation_rules'
    
    def __str__(self):
        return f"{self.name} - {self.company.name}"


class AuditLog(models.Model):
    """Audit trail for all reconciliation actions"""
    ACTION_CHOICES = [
        ('UPLOAD_STATEMENT', 'Upload Statement'),
        ('UPLOAD_RECEIPT', 'Upload Receipt'),
        ('RUN_RECONCILIATION', 'Run Reconciliation'),
        ('AUTO_MATCH', 'Auto Match'),
        ('MANUAL_MATCH', 'Manual Match'),
        ('UNMATCH', 'Unmatch'),
        ('UPDATE_STATUS', 'Update Status'),
        ('DELETE_TRANSACTION', 'Delete Transaction'),
        ('CLEAR_ALL_DATA', 'Clear All Data'),
        ('RESET_FILTERS', 'Reset Filters'),
        ('SYNC_RECEIPTS', 'Sync Receipts'),
        ('PARSE_STATEMENT', 'Parse Statement'),
    ]
    
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='audit_logs')
    user = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, related_name='audit_logs')
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    entity_type = models.CharField(max_length=50)
    entity_id = models.IntegerField(null=True, blank=True)
    details = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'audit_logs'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['company', 'action']),
            models.Index(fields=['timestamp']),
        ]
    
    def __str__(self):
        return f"{self.action} - {self.timestamp}"


class GrantMaster(models.Model):
    grant_name = models.CharField(max_length=255)
    short_name = models.CharField(max_length=50, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.grant_name

    class Meta:
        db_table = 'GrantMaster'
        ordering = ['grant_name']
        constraints = [
            models.UniqueConstraint(
                fields=['grant_name'],
                name='unique_grant_name'
            )
        ]

class Agency(models.Model):
    name = models.CharField(max_length=255)
    short_name = models.CharField(max_length=50, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agencies'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['name'],
                name='unique_agency_name'
            )
        ]

    def __str__(self):
        return self.name


# class Grant(models.Model):
#     company = models.ForeignKey(
#         Company,
#         on_delete=models.CASCADE,
#         related_name='grants'
#     )

#     grant_master = models.ForeignKey(
#         GrantMaster,
#         on_delete=models.PROTECT,
#         related_name='company_grants'
#     )

#     name = models.CharField(max_length=255)

#     description = models.TextField(
#         blank=True,
#         null=True
#     )

#     is_active = models.BooleanField(
#         default=True
#     )

#     created_at = models.DateTimeField(
#         auto_now_add=True
#     )

#     updated_at = models.DateTimeField(
#         auto_now=True
#     )

#     class Meta:
#         db_table = 'grants'
#         ordering = ['name']

#         constraints = [
#             models.UniqueConstraint(
#                 fields=['company', 'name'],
#                 name='unique_grant_per_company'
#             )
#         ]

#     def __str__(self):
#         return self.name



class Grant(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('closed', 'Closed'),
    ]
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='grants'
    )

    agency = models.ForeignKey(
        Agency,
        on_delete=models.PROTECT,
        related_name='grants'
    )

    name = models.CharField(max_length=255)

    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2
    )
    start_date = models.DateField(
        null=True,
        blank=True
    )

    end_date = models.DateField(
        null=True,
        blank=True
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='active'
    )

    description = models.TextField(
        blank=True,
        null=True
    )

    is_active = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        db_table = 'grants'
        ordering = ['name']

        constraints = [
            models.UniqueConstraint(
                fields=['company', 'name'],
                name='unique_grant_per_company'
            )
        ]

    def __str__(self):
        return self.name


class GrantTransaction(models.Model):

    grant = models.ForeignKey(
        Grant,
        on_delete=models.CASCADE,
        related_name='grant_transactions'
    )

    transaction_name = models.CharField(
        max_length=255
    )

    transaction_date = models.DateField()

    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2
    )

    document_information = models.TextField(
        blank=True,
        null=True
    )

    attachment = models.FileField(
        upload_to='grant_transactions/',
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        db_table = 'grant_transactions'
        ordering = ['-transaction_date', '-created_at']

    def __str__(self):
        return f"{self.transaction_name} - ₹{self.amount}"


class GrantMilestone(models.Model):

    grant = models.ForeignKey(
        Grant,
        on_delete=models.CASCADE,
        related_name='milestones'
    )

    name = models.CharField(
        max_length=255
    )

    start_date = models.DateField()

    end_date = models.DateField()

    budget = models.DecimalField(
        max_digits=15,
        decimal_places=2
    )

    attachment = models.FileField(
        upload_to='grant_milestones/',
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        db_table = 'grant_milestones'
        ordering = ['start_date', 'id']

    def __str__(self):
        return self.name


class Fund(models.Model):
    grant = models.ForeignKey(Grant,on_delete=models.CASCADE,related_name='funds')
    source_transaction = models.OneToOneField(Transaction,on_delete=models.PROTECT,related_name='created_fund')
    name = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=15,decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'funds'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['grant', 'name'],
                name='unique_fund_name_per_grant'
            )
        ]

    def __str__(self):
        return f"{self.grant.name} -Fund #{self.name} - ₹{self.amount}"



class TransactionFundAllocation(models.Model):

    ALLOCATION_TYPE_CHOICES = [
        ('source', 'Source'),
        ('destination', 'Destination'),
    ]

    transaction = models.ForeignKey(Transaction,on_delete=models.CASCADE,related_name='fund_allocations')
    fund = models.ForeignKey(Fund,on_delete=models.PROTECT,related_name='transaction_allocations')
    amount = models.DecimalField(max_digits=15,decimal_places=2)
    allocation_type = models.CharField(max_length=15,choices=ALLOCATION_TYPE_CHOICES)
    created_by = models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='created_fund_allocations')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'transaction_fund_allocations'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'transaction',
                    'fund',
                    'allocation_type'
                ],
                name='unique_transaction_fund_allocation'
            )
        ]

    def __str__(self):
        return (
            f"{self.transaction_id} - "
            f"{self.fund.grant.name} - "
            f"Fund #{self.fund_id} - "
            f"₹{self.amount}"
        )





class TransactionGrantAllocation(models.Model):

    ALLOCATION_TYPE_CHOICES = [
        ('source', 'Source'),
        ('destination', 'Destination'),
    ]

    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.CASCADE,
        related_name='grant_allocations'
    )

    grant = models.ForeignKey(
        Grant,
        on_delete=models.PROTECT,
        related_name='transaction_allocations'
    )

    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2
    )

    allocation_type = models.CharField(
        max_length=15,
        choices=ALLOCATION_TYPE_CHOICES
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_grant_allocations'
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        db_table = 'transaction_grant_allocations'
        ordering = ['-created_at']

        constraints = [
            models.UniqueConstraint(
                fields=[
                    'transaction',
                    'grant',
                    'allocation_type'
                ],
                name='unique_transaction_grant_allocation'
            )
        ]

    def __str__(self):
        return (
            f"{self.transaction_id} - "
            f"{self.grant.name} - "
            f"Grant #{self.grant_id} - "
            f"₹{self.amount}"
        )


    

class InternalTransfer(models.Model):
    company = models.ForeignKey(Company,on_delete=models.CASCADE,related_name='internal_transfers')
    transfer_date = models.DateField()
    amount = models.DecimalField(max_digits=15,decimal_places=2)
    created_by = models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='created_internal_transfers')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'internal_transfers'
        ordering = ['-created_at']

    def __str__(self):
        return f"Internal Transfer ₹{self.amount} - {self.transfer_date}"




class InternalTransferTransaction(models.Model):

    TRANSACTION_ROLE_CHOICES = [
        ('source', 'Source'),
        ('destination', 'Destination'),
    ]

    internal_transfer = models.ForeignKey(
        InternalTransfer,
        on_delete=models.CASCADE,
        related_name='transfer_transactions'
    )

    transaction = models.OneToOneField(
        Transaction,
        on_delete=models.PROTECT,
        related_name='internal_transfer_transaction'
    )

    role = models.CharField(
        max_length=15,
        choices=TRANSACTION_ROLE_CHOICES
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        db_table = 'internal_transfer_transactions'

        constraints = [
            models.UniqueConstraint(
                fields=['internal_transfer', 'role'],
                name='unique_internal_transfer_role'
            )
        ]

    def __str__(self):
        return (
            f"Transfer {self.internal_transfer_id} - "
            f"{self.role} - "
            f"Transaction {self.transaction_id}"
        )





class BankStatementConfig(models.Model):

    STRATEGY_CHOICES = [
        ("TABLE", "Table"),
        ("COORDINATE", "Coordinate"),
        ("OCR", "OCR"),
    ]

    bank = models.OneToOneField(
        Bank,
        on_delete=models.CASCADE,
        related_name="statement_config",
    )

    extraction_strategy = models.CharField(
        max_length=30,
        choices=STRATEGY_CHOICES,
    )

    is_active = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return (
            f"{self.bank.short_name or self.bank.bank_name}"
            f" - {self.extraction_strategy}"
        )





class BankStatementFieldAlias(models.Model):

    FIELD_CHOICES = [
        ("date", "Date"),
        ("narration", "Narration"),
        ("ref_no", "Reference Number"),
        ("value_date", "Value Date"),
        ("withdrawal", "Withdrawal"),
        ("deposit", "Deposit"),
        ("balance", "Balance"),
    ]

    config = models.ForeignKey(
        BankStatementConfig,
        on_delete=models.CASCADE,
        related_name="field_aliases",
    )

    field_name = models.CharField(
        max_length=50,
        choices=FIELD_CHOICES,
    )

    alias = models.CharField(
        max_length=150,
    )

    is_active = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "config",
                    "field_name",
                    "alias",
                ],
                name="unique_bank_statement_field_alias",
            )
        ]


    def __str__(self):
        return (
            f"{self.config.bank.short_name or self.config.bank.bank_name}"
            f" - {self.field_name} - {self.alias}"
        )