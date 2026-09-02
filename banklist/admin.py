from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (Bank,Company,User,BankAccount,UploadedStatement,Transaction,ReceiptDocument,ReconciliationRun,ReconciliationRule,
                        AuditLog,Particular,AccountingParticular,Grant,GrantMaster,Fund,TransactionFundAllocation,InternalTransfer,InternalTransferTransaction,
                        BankStatementConfig, BankStatementFieldAlias, Agency, GrantMilestone, GrantTransaction, TransactionGrantAllocation)


@admin.register(Bank)
class BankAdmin(admin.ModelAdmin):
    list_display = ("bank_name", "short_name", "is_active", "created_at")
    search_fields = ("bank_name", "short_name")
    list_filter = ("is_active",)


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User

    list_display = ("email","full_name","company","is_staff","is_active","created_at",)

    list_filter = ("is_staff","is_active","company",)

    search_fields = ("email","full_name",)

    ordering = ("email",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal Info", {"fields": ("full_name", "company")}),
        ("Permissions", {
            "fields": ("is_active","is_staff","is_superuser","groups","user_permissions",)
        }),
        ("Important Dates", {"fields": ("last_login", "created_at")}),
    )

    readonly_fields = ("created_at",)

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email",
                    "full_name",
                    "company",
                    "password1",
                    "password2",
                    "is_staff",
                    "is_active",
                ),
            },
        ),
    )


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = (
        "account_holder_name",
        "account_number",
        "bank",
        "company",
        "created_at",
    )

    search_fields = (
        "account_holder_name",
        "account_number",
        "ifsc_code",
    )

    list_filter = ("bank", "company")


@admin.register(UploadedStatement)
class UploadedStatementAdmin(admin.ModelAdmin):
    list_display = (
        "file_name",
        "bank_account",
        "bank_detected",
        "parsed",
        "uploaded_at",
    )

    search_fields = ("file_name", "bank_detected")
    list_filter = ("parsed", "bank_detected")


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "txn_date",
        "bank_account",
        "txn_type",
        "amount",
        "balance",
        "particular",
        "reconcile_status",
        "accounting_particular_id"
    )

    search_fields = (
        "description",
        "ref_no",
        "utr_no",
    )

    list_filter = (
        "txn_type",
        "reconcile_status",
        "company",
    )


@admin.register(ReceiptDocument)
class ReceiptDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "file_name",
        "company",
        "receipt_no",
        "amount",
        "extraction_error",
        "extracted",
        "uploaded_at",
    )

    search_fields = (
        "file_name",
        "receipt_no",
    )

    list_filter = (
        "company",
        "extracted",
    )


@admin.register(ReconciliationRun)
class ReconciliationRunAdmin(admin.ModelAdmin):
    list_display = (
        "company",
        "run_date",
        "matched_count",
        "unmatched_count",
        "match_percentage",
        "is_auto",
    )

    list_filter = (
        "company",
        "is_auto",
    )


@admin.register(ReconciliationRule)
class ReconciliationRuleAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "company",
        "is_active",
        "auto_match_on_upload",
    )

    list_filter = (
        "company",
        "is_active",
    )


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "action",
        "company",
        "user",
        "entity_type",
        "timestamp",
    )

    search_fields = (
        "action",
        "entity_type",
    )

    list_filter = (
        "action",
        "company",
    )


@admin.register(Particular)
class ParticularAdmin(admin.ModelAdmin):
    list_display = ["id","name","is_active","transaction_type","created_at"]


@admin.register(AccountingParticular)
class AccountParticularAdmin(admin.ModelAdmin):
    list_display = ["id","name","is_active","created_at"]



@admin.register(Agency)
class GrantMasterAdmin(admin.ModelAdmin):
    list_display = ["id","name","short_name","is_active","created_at","updated_at"]


@admin.register(Grant)
class GrantAdmin(admin.ModelAdmin):
    list_display = ["id","company","agency","name","description","is_active","created_at","updated_at"]



@admin.register(Fund)
class FundAdmin(admin.ModelAdmin):
    list_display = ["id","grant","source_transaction","name","amount","created_at","updated_at"]



@admin.register(TransactionFundAllocation)
class TransactionFundAllocationAdmin(admin.ModelAdmin):
    list_display = ["id","transaction","fund","amount","allocation_type","created_by","created_at","updated_at"]


@admin.register(TransactionGrantAllocation)
class TransactionFundAllocationAdmin(admin.ModelAdmin):
    list_display = ["id","transaction","grant","amount","allocation_type","created_by","created_at","updated_at"]



@admin.register(InternalTransfer)
class InternalTransferAdmin(admin.ModelAdmin):
    list_display = ["id","company","transfer_date","amount","created_by","created_at","updated_at"]



@admin.register(InternalTransferTransaction)
class InternalTransferTransactionAdmin(admin.ModelAdmin):
    list_display = ["id","internal_transfer","transaction","role"]



@admin.register(BankStatementConfig)
class BankStatementConfigAdmin(admin.ModelAdmin):
    list_display = ["id","bank","extraction_strategy","is_active"]



@admin.register(BankStatementFieldAlias)
class BankStatementFieldAliasAdmin(admin.ModelAdmin):
    list_display = ["id","config","field_name","alias","is_active"]


@admin.register(GrantTransaction)
class GrantTransactionAdmin(admin.ModelAdmin):
    list_display = ["id","grant","transaction_name","transaction_date"]

@admin.register(GrantMilestone)
class GrantMilestone(admin.ModelAdmin):
    list_display = ["id","grant","name","budget"]