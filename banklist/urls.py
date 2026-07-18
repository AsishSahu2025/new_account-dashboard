from django.urls import path
from .views import (
    search_banks,
    register,
    login,
    logout,
    list_bank_accounts,
    delete_bank_account,
    init_company_folder,
    create_drive_folder,
    create_drive_folder_async,
    upload_to_drive,
    upload_to_drive_async,
    task_status,
    upload_receipt,
    sync_receipt_folder,
    list_receipts,
    extract_receipts,
    parse_statement,
    list_transactions,
    run_reconciliation_view,
    reconciliation_stats,
    list_statements,
    # ========== NEW IMPORTS FOR RECONCILIATION ==========
    dashboard_summary,
    run_full_reconciliation_view,
    match_receipts_view,
    reconciliation_history,
    get_audit_log,
    clear_all_data,
)

from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    # Auth URLs
    path('auth/register/', register, name='register'),
    path('auth/login/', login, name='login'),
    path('auth/logout/', logout, name='logout'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    
    # Bank URLs
    path('banks/search/', search_banks, name='search_banks'),
    path('bank-accounts/', list_bank_accounts, name='list_bank_accounts'),
    path('bank-accounts/<int:account_id>/delete/', delete_bank_account, name='delete_bank_account'),
    path('banks/init-company-folder/', init_company_folder, name='init_company_folder'),
    path('banks/create-folder/', create_drive_folder, name='create_drive_folder'),
    path('banks/create-folder/async/', create_drive_folder_async, name='create_drive_folder_async'),
    path('banks/upload-file/', upload_to_drive, name='upload_to_drive'),
    path('banks/upload-file/async/', upload_to_drive_async, name='upload_to_drive_async'),
    path('tasks/<str:task_id>/status/', task_status, name='task_status'),
    
    # Receipt URLs
    path('receipts/upload/', upload_receipt, name='upload_receipt'),
    path('receipts/sync-folder/', sync_receipt_folder, name='sync_receipt_folder'),
    path('receipts/list/', list_receipts, name='list_receipts'),
    path('receipts/extract/', extract_receipts, name='extract_receipts'),
    
    # Reconciliation URLs (Existing)
    path('reconciliation/parse-statement/', parse_statement, name='parse_statement'),
    path('reconciliation/transactions/', list_transactions, name='list_transactions'),
    path('reconciliation/run/', run_reconciliation_view, name='run_reconciliation'),
    path('reconciliation/stats/', reconciliation_stats, name='reconciliation_stats'),
    path('reconciliation/statements/', list_statements, name='list_statements'),
    
    # ========== NEW RECONCILIATION URLs ==========
    path('reconciliation/dashboard-summary/', dashboard_summary, name='dashboard-summary'),
    path('reconciliation/run-full/', run_full_reconciliation_view, name='run-full-reconciliation'),
    path('reconciliation/match-receipts/', match_receipts_view, name='match-receipts'),
    path('reconciliation/history/', reconciliation_history, name='reconciliation-history'),
    path('reconciliation/audit-log/', get_audit_log, name='audit-log'),
    path('reconciliation/clear-all/', clear_all_data, name='clear-all-data'),
]