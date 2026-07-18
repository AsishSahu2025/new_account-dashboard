from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    Bank,
    Company,
    User,
    BankAccount,
    UploadedStatement,
    Transaction,
    ReceiptDocument,
    ReconciliationRun,
    ReconciliationRule,
    AuditLog,
)


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

    list_display = (
        "email",
        "full_name",
        "company",
        "is_staff",
        "is_active",
        "created_at",
    )

    list_filter = (
        "is_staff",
        "is_active",
        "company",
    )

    search_fields = (
        "email",
        "full_name",
    )

    ordering = ("email",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal Info", {"fields": ("full_name", "company")}),
        ("Permissions", {
            "fields": (
                "is_active",
                "is_staff",
                "is_superuser",
                "groups",
                "user_permissions",
            )
        }),
        ("Important Dates", {"fields": ("last_login", "created_at")}),
    )

    readonly_fields = ("created_at",)

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
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
        "txn_date",
        "bank_account",
        "txn_type",
        "amount",
        "balance",
        "reconcile_status",
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