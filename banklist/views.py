# banklist/views.py

import io
import logging
from decimal import Decimal
from datetime import datetime
from django.db.models import Q, Count, Sum
from django.utils import timezone
from django.core.cache import cache

from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework_simplejwt.tokens import RefreshToken

from celery.result import AsyncResult
import re

from .models import (
    Bank, BankAccount, Transaction, UploadedStatement,
    ReceiptDocument, Company, User, ReconciliationRun,
    ReconciliationRule, AuditLog
)
from .serializers import (
    BankSerializer, BankAccountSerializer, TransactionSerializer,
    UploadedStatementSerializer, ReceiptDocumentSerializer,
    ReconciliationRunSerializer, ReconciliationRuleSerializer,
    AuditLogSerializer, RegisterSerializer, LoginSerializer
)
from .services.google_drive_service import drive_service
from .services.pdf_parser import parse_bank_statement
from .services.receipt_parser import parse_receipt_pdf, extract_receipt_data
from .services.reconciliation_engine import run_reconciliation
from .services.enhanced_reconciliation_engine import (
    run_full_reconciliation,
    match_with_receipts_only
)
from .tasks import (
    create_drive_folder_task,
    upload_to_drive_task,
    parse_statement_task,
    process_receipt_task,
    process_all_receipts_task,
    run_reconciliation_task
)

logger = logging.getLogger(__name__)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def _get_company_name(request):
    try:
        user = request.user
        if user.company:
            return user.company.name
        return user.full_name or user.email
    except Exception as e:
        logger.error(f"Error getting company name: {e}")
        return None


def _parse_drive_timestamp(ts: str):
    """
    Parse Google Drive ISO timestamp: '2026-06-28T10:20:59.000Z'
    Returns a timezone-aware datetime or None.

    FIX: views.py was calling _parse_date() on this format which
    only handles dd/mm/yyyy style — always returned None.
    """
    if not ts:
        return None
    try:
        # Strip milliseconds if present
        ts_clean = re.sub(r'\.\d+Z$', 'Z', ts)
        dt = datetime.strptime(ts_clean, '%Y-%m-%dT%H:%M:%SZ')
        return timezone.make_aware(dt, timezone.utc)
    except Exception:
        return None


def _parse_date(date_str):
    """Parse dd/mm/yyyy style date strings (used for bank statement dates)."""
    if not date_str:
        return None
    date_str = str(date_str).strip()
    formats = [
        '%d/%m/%Y', '%d-%m-%Y', '%d/%m/%y', '%d-%m-%y',
        '%d-%b-%Y', '%d-%b-%y', '%d %b %Y', '%d %b %y',
        '%Y-%m-%d', '%Y/%m/%d', '%d.%m.%Y', '%d.%m.%y'
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def _extract_receipt_text(file_bytes, mime_type):
    """Extract text from receipt with OCR fallback."""
    if not file_bytes:
        return ""
    try:
        import pdfplumber
        import fitz
        from PIL import Image
        import pytesseract

        extracted_text = ""
        if mime_type == "application/pdf":
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                extracted_text = "\n".join(
                    page.extract_text() or "" for page in pdf.pages
                ).strip()

        ocr_needed = (
            mime_type != "application/pdf" or
            len(extracted_text) < 200 or
            not re.search(r"(₹|INR|Rs\.?)", extracted_text, re.I)
        )

        if not ocr_needed:
            return extracted_text

        if mime_type == "application/pdf":
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            pages = []
            for page in doc:
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                pages.append(pytesseract.image_to_string(img, lang="eng"))
            return "\n".join(pages).strip()

        return pytesseract.image_to_string(
            Image.open(io.BytesIO(file_bytes)), lang="eng"
        ).strip()

    except Exception as e:
        logger.error(f"Receipt text extraction failed: {e}")
        return ""


# ============================================================
# AUTHENTICATION VIEWS
# ============================================================

@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    serializer = RegisterSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = serializer.save()
    refresh = RefreshToken.for_user(user)

    return Response({
        'success': True,
        'message': 'Account created successfully',
        'user': {
            'id': user.id,
            'email': user.email,
            'full_name': user.full_name,
            'company': user.company.name,
        },
        'tokens': {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    serializer = LoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = serializer.validated_data['user']
    refresh = RefreshToken.for_user(user)

    return Response({
        'success': True,
        'message': 'Login successful',
        'user': {
            'id': user.id,
            'email': user.email,
            'full_name': user.full_name,
            'company': user.company.name if user.company else None,
        },
        'tokens': {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def logout(request):
    try:
        token = RefreshToken(request.data.get('refresh'))
        token.blacklist()
        return Response({'success': True, 'message': 'Logged out'})
    except Exception:
        return Response({'error': 'Invalid token'}, status=status.HTTP_400_BAD_REQUEST)


# ============================================================
# BANK MANAGEMENT VIEWS
# ============================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search_banks(request):
    search_term = request.GET.get('search', '').strip()
    banks = (
        Bank.objects.filter(bank_name__icontains=search_term, is_active=True)
        if search_term else
        Bank.objects.filter(is_active=True)
    )
    return Response([
        {'bank_name': b.bank_name, 'short_name': b.short_name, 'id': b.id}
        for b in banks
    ])


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_bank_accounts(request):
    company = request.user.company
    if not company:
        return Response({'error': 'User has no company'}, status=400)
    accounts = BankAccount.objects.filter(company=company).select_related('bank')
    return Response(BankAccountSerializer(accounts, many=True).data)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_bank_account(request, account_id):
    try:
        bank_account = BankAccount.objects.get(
            id=account_id, company=request.user.company
        )
    except BankAccount.DoesNotExist:
        return Response({'error': 'Bank account not found'}, status=404)

    try:
        bank_name    = str(bank_account)
        drive_errors = []

        if bank_account.bank_folder_id:
            try:
                if not drive_service.delete_folder(bank_account.bank_folder_id):
                    drive_errors.append('Could not delete Drive folder')
            except Exception as e:
                logger.error(f"Drive delete error: {e}")
                drive_errors.append(str(e))

        bank_account.delete()

        return Response({
            'success': True,
            'message': f'"{bank_name}" deleted successfully',
            'drive_warnings': drive_errors,
        })

    except Exception as e:
        logger.error(f"Delete error: {e}", exc_info=True)
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def init_company_folder(request):
    company_name = _get_company_name(request)
    if not company_name:
        return Response({'error': 'Could not determine company/user name'}, status=400)

    result = drive_service.get_or_create_company_folder(company_name)
    if not result:
        return Response({'error': 'Failed to create company folder'}, status=500)

    return Response({
        'success': True,
        'message': f'Company folder ready: {company_name}',
        'company_name': company_name,
        'company_folder_id': result['company_folder_id'],
        'subfolders': result['subfolders'],
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_drive_folder(request):
    bank_name      = request.data.get('bank_name')
    account_holder = request.data.get('account_holder_name')
    account_number = request.data.get('account_number')
    ifsc_code      = request.data.get('ifsc_code', '')

    if not bank_name:
        return Response({'error': 'bank_name is required'}, status=400)

    bank = Bank.objects.filter(bank_name=bank_name).first()
    if not bank:
        return Response({'error': f'Bank {bank_name} not found'}, status=404)

    folder_name  = f"{bank_name} - {account_holder} - {account_number}"
    company_name = _get_company_name(request)

    drive_result = drive_service.create_bank_folder_structure(
        folder_name, company_name=company_name
    )
    if not drive_result['success']:
        return Response({'error': drive_result['message']}, status=500)

    bank_account, _ = BankAccount.objects.get_or_create(
        company=request.user.company,
        bank=bank,
        account_number=account_number,
        defaults={
            'account_holder_name': account_holder,
            'ifsc_code':           ifsc_code,
            'bank_folder_id':      drive_result.get('bank_folder_id'),
            'statement_folder_id': drive_result.get('statement_folder_id'),
            'drive_link':          drive_result.get('bank_folder_link'),
        }
    )

    return Response({
        'success': True,
        'message': f'Google Drive folders created for {folder_name}',
        'bank_account': BankAccountSerializer(bank_account).data,
        'drive_folders': {'total_folders': drive_result.get('total_folders_created', 0)},
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_drive_folder_async(request):
    bank_name      = request.data.get('bank_name')
    account_holder = request.data.get('account_holder_name')
    account_number = request.data.get('account_number')

    if not bank_name:
        return Response({'error': 'bank_name is required'}, status=400)
    if not Bank.objects.filter(bank_name=bank_name).exists():
        return Response({'error': f'Bank {bank_name} not found'}, status=404)

    folder_name  = f"{bank_name} - {account_holder} - {account_number}"
    company_name = _get_company_name(request)
    task         = create_drive_folder_task.delay(folder_name, company_name=company_name)

    return Response({
        'success':    True,
        'message':    'Folder creation queued',
        'task_id':    task.id,
        'status_url': f"/api/tasks/{task.id}/status/",
    }, status=status.HTTP_202_ACCEPTED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def task_status(request, task_id):
    task_result = AsyncResult(task_id)
    response = {
        'task_id':    task_id,
        'status':     task_result.status,
        'ready':      task_result.ready(),
        'successful': task_result.successful() if task_result.ready() else None,
        'failed':     task_result.failed()     if task_result.ready() else None,
    }
    if task_result.ready():
        if task_result.successful():
            response['result'] = task_result.result
        elif task_result.failed():
            response['error'] = str(task_result.result)
    return Response(response)


# ============================================================
# STATEMENT UPLOAD & PARSING VIEWS
# ============================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def upload_to_drive(request):
    try:
        bank_name          = request.data.get('bank_name')
        statement_folder_id = request.data.get('statement_folder_id')
        uploaded_file      = request.FILES.get('file')

        if not all([bank_name, statement_folder_id, uploaded_file]):
            return Response(
                {'error': 'bank_name, statement_folder_id, and file are required'},
                status=400
            )

        allowed = {
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'application/pdf', 'image/jpeg', 'image/png',
        }
        if uploaded_file.content_type not in allowed:
            return Response({'error': f'Unsupported file type: {uploaded_file.content_type}'}, status=400)

        result = drive_service.upload_file(
            file_obj=uploaded_file,
            file_name=uploaded_file.name,
            folder_id=statement_folder_id,
            mime_type=uploaded_file.content_type,
        )
        if not result:
            return Response({'error': 'Failed to upload to Drive'}, status=500)

        return Response({'success': True, 'message': 'File uploaded', 'file': result},
                        status=status.HTTP_201_CREATED)

    except Exception as e:
        logger.error(f"Upload error: {e}")
        return Response({'error': str(e)}, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def upload_to_drive_async(request):
    bank_name          = request.data.get('bank_name')
    statement_folder_id = request.data.get('statement_folder_id')
    uploaded_file      = request.FILES.get('file')

    if not all([bank_name, statement_folder_id, uploaded_file]):
        return Response({'error': 'bank_name, statement_folder_id, and file are required'}, status=400)

    allowed = {
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/pdf', 'image/jpeg', 'image/png',
    }
    if uploaded_file.content_type not in allowed:
        return Response({'error': f'Unsupported file type: {uploaded_file.content_type}'}, status=400)

    task = upload_to_drive_task.delay(
        uploaded_file.read(), uploaded_file.name,
        statement_folder_id, uploaded_file.content_type,
    )
    return Response({
        'success':    True,
        'message':    'File upload queued',
        'task_id':    task.id,
        'status_url': f"/api/tasks/{task.id}/status/",
    }, status=status.HTTP_202_ACCEPTED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def parse_statement(request):
    bank_account_id = request.data.get('bank_account_id')
    uploaded_file   = request.FILES.get('file')

    if not bank_account_id or not uploaded_file:
        return Response({'error': 'bank_account_id and file are required'}, status=400)

    try:
        bank_account = BankAccount.objects.get(
            id=bank_account_id, company=request.user.company
        )
    except BankAccount.DoesNotExist:
        return Response({'error': 'Bank account not found'}, status=404)

    file_bytes = uploaded_file.read()

    stmt = UploadedStatement.objects.create(
        bank_account=bank_account,
        file_name=uploaded_file.name,
        parsed=False,
    )

    result = drive_service.upload_file(
        file_obj=io.BytesIO(file_bytes),
        file_name=uploaded_file.name,
        folder_id=bank_account.statement_folder_id,
        mime_type=uploaded_file.content_type,
    )

    if not result:
        stmt.delete()
        return Response({'error': 'Failed to upload file to Drive'}, status=500)

    stmt.drive_file_id = result.get('file_id')
    stmt.save(update_fields=['drive_file_id'])

    task = parse_statement_task.delay(stmt.id)

    return Response({
        'success':      True,
        'message':      'Statement uploaded and queued for processing',
        'statement_id': stmt.id,
        'task_id':      task.id,
        'status_url':   f"/api/tasks/{task.id}/status/",
    }, status=status.HTTP_202_ACCEPTED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_statements(request):
    qs = UploadedStatement.objects.filter(
        bank_account__company=request.user.company
    ).order_by('-uploaded_at')

    bank_account_id = request.query_params.get('bank_account_id')
    if bank_account_id:
        qs = qs.filter(bank_account_id=bank_account_id)

    return Response(UploadedStatementSerializer(qs, many=True).data)


# ============================================================
# RECEIPT MANAGEMENT VIEWS
# ============================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def upload_receipt(request):
    try:
        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return Response({'error': 'file is required'}, status=400)

        allowed = {
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'application/pdf', 'image/jpeg', 'image/png',
        }
        if uploaded_file.content_type not in allowed:
            return Response({'error': f'Unsupported file type: {uploaded_file.content_type}'}, status=400)

        company_name = _get_company_name(request)
        if not company_name:
            return Response({'error': 'Could not determine company name'}, status=400)

        company_result = drive_service.get_or_create_company_folder(company_name)
        if not company_result:
            return Response({'error': 'Could not access company Drive folder'}, status=500)

        billing_folder_id = company_result['subfolders'].get('Billing_Receipt')
        if not billing_folder_id:
            return Response({'error': 'Billing_Receipt folder not found'}, status=500)

        file_bytes = uploaded_file.read()

        result = drive_service.upload_file(
            file_obj=io.BytesIO(file_bytes),
            file_name=uploaded_file.name,
            folder_id=billing_folder_id,
            mime_type=uploaded_file.content_type,
        )
        if not result:
            return Response({'error': 'Failed to upload to Drive'}, status=500)

        # FIX: use timezone.now() not datetime.now() to avoid TZ crash
        receipt = ReceiptDocument.objects.create(
            company=request.user.company,
            drive_file_id=result.get('file_id'),
            file_name=uploaded_file.name,
            file_link=result.get('file_link'),
            mime_type=uploaded_file.content_type,
            uploaded_at=timezone.now(),
            extracted=False,
        )

        task = process_receipt_task.delay(receipt.id)

        return Response({
            'success':    True,
            'message':    'Receipt uploaded and queued for processing',
            'receipt_id': receipt.id,
            'task_id':    task.id,
            'status_url': f"/api/tasks/{task.id}/status/",
        }, status=status.HTTP_202_ACCEPTED)

    except Exception as e:
        logger.error(f"Error uploading receipt: {e}", exc_info=True)
        return Response({'error': str(e)}, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def sync_receipt_folder(request):
    company_name = _get_company_name(request)
    if not company_name:
        return Response({'error': 'Could not determine company name'}, status=400)

    company_result = drive_service.get_or_create_company_folder(company_name)
    if not company_result:
        return Response({'error': 'Could not access company Drive folder'}, status=500)

    billing_folder_id = company_result['subfolders'].get('Billing_Receipt')
    if not billing_folder_id:
        return Response({'error': 'Billing_Receipt folder not found'}, status=500)

    files         = drive_service.list_files(billing_folder_id)
    created_count = 0
    updated_count = 0

    for f in files:
        # FIX: Drive timestamps are ISO format '2026-06-28T10:20:59.000Z'
        # use _parse_drive_timestamp() not _parse_date()
        uploaded_at = _parse_drive_timestamp(f.get('createdTime', ''))

        _, created = ReceiptDocument.objects.update_or_create(
            company=request.user.company,
            drive_file_id=f.get('id', ''),
            defaults={
                'file_name':  f.get('name', ''),
                'file_link':  f.get('webViewLink', ''),
                'mime_type':  f.get('mimeType', ''),
                'uploaded_at': uploaded_at or timezone.now(),
            },
        )
        if created:
            created_count += 1
        else:
            updated_count += 1

    return Response({
        'success':          True,
        'folder_id':        billing_folder_id,
        'total_files_seen': len(files),
        'created':          created_count,
        'updated':          updated_count,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_receipts(request):
    # FIX: order only by uploaded_at — created_at may not exist on the model
    qs = ReceiptDocument.objects.filter(
        company=request.user.company
    ).order_by('-uploaded_at')

    extracted = request.query_params.get('extracted')
    if extracted in ('true', 'false'):
        qs = qs.filter(extracted=(extracted == 'true'))

    search = request.query_params.get('search')
    if search:
        qs = qs.filter(
            Q(file_name__icontains=search) | Q(receipt_no__icontains=search)
        )

    page      = int(request.query_params.get('page', 1))
    page_size = int(request.query_params.get('page_size', 50))
    start     = (page - 1) * page_size
    end       = start + page_size
    total     = qs.count()

    return Response({
        'count':   total,
        'page':    page,
        'pages':   (total + page_size - 1) // page_size,
        'results': ReceiptDocumentSerializer(qs[start:end], many=True).data,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def extract_receipts(request):
    receipt_ids = request.data.get('receipt_ids')
    qs = ReceiptDocument.objects.filter(company=request.user.company, extracted=False)
    if receipt_ids:
        qs = qs.filter(id__in=receipt_ids)

    if not qs.exists():
        return Response({
            'success': True, 'message': 'No receipts to extract',
            'processed': 0, 'extracted': 0, 'failed': 0,
        })

    processed    = 0
    extracted_ok = 0
    failed       = 0
    errors       = []

    for receipt in qs:
        processed += 1
        try:
            file_bytes = drive_service.download_file(receipt.drive_file_id)
            if not file_bytes:
                receipt.extracted        = False
                receipt.extraction_error = 'Failed to download from Drive'
                receipt.save(update_fields=['extracted', 'extraction_error'])
                failed += 1
                errors.append(f"{receipt.file_name}: Download failed")
                continue

            result = parse_receipt_pdf(file_bytes, receipt.file_name)

            receipt.receipt_no   = result.get('receipt_no')   or receipt.receipt_no
            receipt.receipt_date = result.get('receipt_date') or receipt.receipt_date

            amount_val = result.get('amount')
            if amount_val is None:
                receipt.extracted        = False
                receipt.extraction_error = result.get('error', 'Could not extract amount')
                failed += 1
                errors.append(f"{receipt.file_name}: {receipt.extraction_error}")
            else:
                receipt.amount           = amount_val
                receipt.extracted        = True
                receipt.extraction_error = ''
                extracted_ok += 1

            receipt.save(update_fields=[
                'receipt_no', 'receipt_date', 'amount', 'extracted', 'extraction_error'
            ])

        except Exception as exc:
            logger.error(f"Receipt {receipt.file_name}: {exc}", exc_info=True)
            receipt.extracted        = False
            receipt.extraction_error = str(exc)
            receipt.save(update_fields=['extracted', 'extraction_error'])
            failed += 1
            errors.append(f"{receipt.file_name}: {str(exc)}")

    return Response({
        'success':   True,
        'message':   f'Extracted {extracted_ok}, failed {failed}',
        'processed': processed,
        'extracted': extracted_ok,
        'failed':    failed,
        'errors':    errors[:10],
    })


# ============================================================
# TRANSACTION VIEWS
# ============================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_transactions(request):
    qs = Transaction.objects.filter(company=request.user.company)

    bank_account_id = request.query_params.get('bank_account_id')
    rec_status      = request.query_params.get('status')
    date_from       = request.query_params.get('date_from')
    date_to         = request.query_params.get('date_to')
    search          = request.query_params.get('search')

    if bank_account_id: qs = qs.filter(bank_account_id=bank_account_id)
    if rec_status:      qs = qs.filter(reconcile_status=rec_status)
    if date_from:       qs = qs.filter(txn_date__gte=date_from)
    if date_to:         qs = qs.filter(txn_date__lte=date_to)
    if search:
        qs = qs.filter(
            Q(description__icontains=search) |
            Q(utr_no__icontains=search)      |
            Q(ref_no__icontains=search)
        )

    qs        = qs.select_related('bank_account__bank').order_by('-txn_date')
    page      = int(request.query_params.get('page', 1))
    page_size = int(request.query_params.get('page_size', 50))
    start     = (page - 1) * page_size
    total     = qs.count()

    return Response({
        'count':   total,
        'page':    page,
        'pages':   (total + page_size - 1) // page_size,
        'results': TransactionSerializer(qs[start:start + page_size], many=True).data,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def reconciliation_stats(request):
    company = request.user.company
    acc1_id = request.query_params.get('bank_account_1')
    acc2_id = request.query_params.get('bank_account_2')

    qs = Transaction.objects.filter(company=company)
    if acc1_id and acc2_id:
        qs = qs.filter(bank_account_id__in=[acc1_id, acc2_id])

    return Response(qs.aggregate(
        total=Count('id'),
        total_matched=Count('id', filter=Q(reconcile_status='matched')),
        total_unmatched=Count('id', filter=Q(reconcile_status='unmatched')),
        total_receipt_missing=Count('id', filter=Q(reconcile_status='receipt_missing')),
    ))


# ============================================================
# RECONCILIATION VIEWS
# ============================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def run_reconciliation_view(request):
    acc1_id   = request.data.get('bank_account_1')
    acc2_id   = request.data.get('bank_account_2')
    date_from = request.data.get('date_from')
    date_to   = request.data.get('date_to')

    if not acc1_id or not acc2_id:
        return Response({'error': 'bank_account_1 and bank_account_2 are required'}, status=400)

    result = run_reconciliation(
        bank_account_1_id=int(acc1_id),
        bank_account_2_id=int(acc2_id),
        company_id=request.user.company.id,
        date_from=date_from,
        date_to=date_to,
    )

    if 'error' in result:
        return Response(result, status=400)
    return Response({'success': True, **result})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_summary(request):
    company   = request.user.company
    cache_key = f'dashboard_summary_{company.id}'
    cached    = cache.get(cache_key)
    if cached:
        return Response(cached)

    bank_accounts = BankAccount.objects.filter(company=company)
    transactions  = Transaction.objects.filter(company=company)

    total_transactions = transactions.count()
    matched_count      = transactions.filter(reconcile_status='matched').count()
    receipt_missing    = transactions.filter(reconcile_status='receipt_missing').count()
    unmatched          = transactions.filter(reconcile_status='unmatched').count()
    ignored            = transactions.filter(reconcile_status='ignored').count()

    # FIX: use separate denominator variable — don't overwrite total_transactions
    denom = total_transactions or 1
    matched_pct        = matched_count   / denom * 100
    receipt_missing_pct = receipt_missing / denom * 100
    unmatched_pct      = unmatched       / denom * 100

    last_reconciliation = ReconciliationRun.objects.filter(company=company).first()

    bank_summaries = []
    for ba in bank_accounts:
        last_stmt = ba.statements.filter(parsed=True).order_by('-uploaded_at').first()
        bank_summaries.append({
            'id':               ba.id,
            'bank_name':        ba.bank.bank_name,
            'account_holder':   ba.account_holder_name,
            'account_number':   ba.account_number,
            'ifsc':             ba.ifsc_code or 'N/A',
            'last_synced':      last_stmt.uploaded_at if last_stmt else None,
            'transaction_count': ba.transactions.count(),
            'matched_count':    ba.transactions.filter(reconcile_status='matched').count(),
        })

    # 24h stats — FIX: keep raw count separate from the display value
    last_24h          = timezone.now() - timezone.timedelta(hours=24)
    txns_24h          = transactions.filter(created_at__gte=last_24h)
    total_24h_raw     = txns_24h.count()
    matched_24h       = txns_24h.filter(reconcile_status='matched').count()
    missing_24h       = txns_24h.filter(reconcile_status='receipt_missing').count()
    unmatched_24h     = txns_24h.filter(reconcile_status='unmatched').count()
    denom_24h         = total_24h_raw or 1   # separate variable — don't corrupt total_24h_raw

    data = {
        'total_transactions':       total_transactions,
        'matched':                  matched_count,
        'matched_percentage':       round(matched_pct, 1),
        'receipt_missing':          receipt_missing,
        'receipt_missing_percentage': round(receipt_missing_pct, 1),
        'unmatched':                unmatched,
        'unmatched_percentage':     round(unmatched_pct, 1),
        'ignored':                  ignored,
        'last_reconciliation':      last_reconciliation.run_date if last_reconciliation else None,
        'last_reconciliation_id':   last_reconciliation.id       if last_reconciliation else None,
        'banks':                    bank_summaries,
        'last_24h': {
            'total':                     total_24h_raw,   # FIX: real count not the `or 1` value
            'matched':                   matched_24h,
            'matched_percentage':        round(matched_24h / denom_24h * 100, 1),
            'receipt_missing':           missing_24h,
            'receipt_missing_percentage': round(missing_24h / denom_24h * 100, 1),
            'unmatched':                 unmatched_24h,
            'unmatched_percentage':      round(unmatched_24h / denom_24h * 100, 1),
        },
    }

    cache.set(cache_key, data, 300)
    return Response(data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def run_full_reconciliation_view(request):
    company    = request.user.company
    acc1_id    = request.data.get('bank_account_1')
    acc2_id    = request.data.get('bank_account_2')
    date_from  = request.data.get('date_from')
    date_to    = request.data.get('date_to')
    auto_match = request.data.get('auto_match', True)
    async_mode = request.data.get('async', False)

    if not acc1_id or not acc2_id:
        return Response({'error': 'bank_account_1 and bank_account_2 are required'}, status=400)

    try:
        if async_mode:
            task = run_reconciliation_task.delay(
                company_id=company.id,
                bank_account_1_id=int(acc1_id),
                bank_account_2_id=int(acc2_id),
                date_from=date_from,
                date_to=date_to,
                auto_match=auto_match,
            )
            return Response({
                'success':    True,
                'message':    'Reconciliation queued',
                'task_id':    task.id,
                'status_url': f"/api/tasks/{task.id}/status/",
            }, status=status.HTTP_202_ACCEPTED)

        result = run_full_reconciliation(
            company=company,
            user=request.user,
            bank_account_1_id=int(acc1_id),
            bank_account_2_id=int(acc2_id),
            date_from=date_from,
            date_to=date_to,
            auto_match=auto_match,
        )

        AuditLog.objects.create(
            company=company,
            user=request.user,
            action='AUTO_MATCH' if auto_match else 'RUN_RECONCILIATION',
            entity_type='RECONCILIATION',
            entity_id=result['run_id'],
            details={
                'bank_account_1': acc1_id,
                'bank_account_2': acc2_id,
                'summary': result['summary'],
            },
        )
        cache.delete(f'dashboard_summary_{company.id}')
        return Response({'success': True, **result})

    except Exception as e:
        logger.error(f"Reconciliation failed: {e}", exc_info=True)
        return Response({'error': str(e)}, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def match_receipts_view(request):
    company        = request.user.company
    bank_account_id = request.data.get('bank_account_id')

    result = match_with_receipts_only(
        company=company,
        bank_account_id=bank_account_id,
        user=request.user,
    )

    AuditLog.objects.create(
        company=company,
        user=request.user,
        action='AUTO_MATCH',
        entity_type='RECEIPT_MATCHING',
        entity_id=0,
        details={'result': result},
    )
    cache.delete(f'dashboard_summary_{company.id}')
    return Response({'success': True, **result})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def reconciliation_history(request):
    company = request.user.company
    runs    = ReconciliationRun.objects.filter(company=company)

    bank_id   = request.query_params.get('bank_id')
    date_from = request.query_params.get('date_from')
    date_to   = request.query_params.get('date_to')

    if bank_id:
        runs = runs.filter(Q(bank_account_1_id=bank_id) | Q(bank_account_2_id=bank_id))
    if date_from: runs = runs.filter(run_date__gte=date_from)
    if date_to:   runs = runs.filter(run_date__lte=date_to)

    page      = int(request.query_params.get('page', 1))
    page_size = int(request.query_params.get('page_size', 20))
    start     = (page - 1) * page_size
    total     = runs.count()

    return Response({
        'count':   total,
        'page':    page,
        'pages':   (total + page_size - 1) // page_size,
        'results': ReconciliationRunSerializer(runs[start:start + page_size], many=True).data,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_audit_log(request):
    company    = request.user.company
    audit_logs = AuditLog.objects.filter(company=company)

    action    = request.query_params.get('action')
    date_from = request.query_params.get('date_from')
    date_to   = request.query_params.get('date_to')
    user_id   = request.query_params.get('user_id')

    if action:    audit_logs = audit_logs.filter(action=action)
    if date_from: audit_logs = audit_logs.filter(timestamp__gte=date_from)
    if date_to:   audit_logs = audit_logs.filter(timestamp__lte=date_to)
    if user_id:   audit_logs = audit_logs.filter(user_id=user_id)

    page      = int(request.query_params.get('page', 1))
    page_size = int(request.query_params.get('page_size', 50))
    start     = (page - 1) * page_size
    total     = audit_logs.count()

    return Response({
        'count':   total,
        'page':    page,
        'pages':   (total + page_size - 1) // page_size,
        'results': AuditLogSerializer(audit_logs[start:start + page_size], many=True).data,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def clear_all_data(request):
    company = request.user.company

    if not request.data.get('confirm', False):
        return Response({'error': 'Confirmation required. Set confirm=true'}, status=400)

    txn_count  = Transaction.objects.filter(company=company).count()
    stmt_count = UploadedStatement.objects.filter(bank_account__company=company).count()
    run_count  = ReconciliationRun.objects.filter(company=company).count()

    Transaction.objects.filter(company=company).delete()
    UploadedStatement.objects.filter(bank_account__company=company).delete()
    ReconciliationRun.objects.filter(company=company).delete()

    AuditLog.objects.create(
        company=company,
        user=request.user,
        action='CLEAR_ALL_DATA',
        entity_type='ALL',
        entity_id=0,
        details={
            'transactions_deleted': txn_count,
            'statements_deleted':   stmt_count,
            'runs_deleted':         run_count,
        },
    )
    cache.delete(f'dashboard_summary_{company.id}')

    return Response({
        'message': 'All data cleared successfully',
        'deleted': {
            'transactions':        txn_count,
            'statements':          stmt_count,
            'reconciliation_runs': run_count,
        },
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def extraction_status(request):
    company      = request.user.company
    statements   = UploadedStatement.objects.filter(bank_account__company=company)
    transactions = Transaction.objects.filter(company=company)
    receipts     = ReceiptDocument.objects.filter(company=company)

    total            = transactions.count()
    matched          = transactions.filter(reconcile_status='matched').count()
    receipt_missing  = transactions.filter(reconcile_status='receipt_missing').count()
    unmatched        = transactions.filter(reconcile_status='unmatched').count()
    total_receipts   = receipts.count()
    extracted        = receipts.filter(extracted=True).count()

    return Response({
        'statements': {
            'total':  statements.count(),
            'parsed': statements.filter(parsed=True).count(),
            'failed': statements.filter(parsed=False).count(),
        },
        'transactions': {
            'total':          total,
            'matched':        matched,
            'receipt_missing': receipt_missing,
            'unmatched':      unmatched,
            'match_percentage': round(matched / total * 100 if total else 0, 1),
        },
        'receipts': {
            'total':                total_receipts,
            'extracted':            extracted,
            'failed':               total_receipts - extracted,
            'extraction_percentage': round(extracted / total_receipts * 100 if total_receipts else 0, 1),
        },
        'is_complete': (
            statements.filter(parsed=False).count() == 0 and
            receipts.filter(extracted=False).count() == 0 and
            total > 0
        ),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def verification_extraction(request):
    company      = request.user.company
    statements   = UploadedStatement.objects.filter(bank_account__company=company)
    transactions = Transaction.objects.filter(company=company)
    receipts     = ReceiptDocument.objects.filter(company=company)

    total_receipts     = receipts.count()
    extracted_receipts = receipts.filter(extracted=True).count()
    matched            = transactions.filter(reconcile_status='matched').count()
    receipt_missing    = transactions.filter(reconcile_status='receipt_missing').count()
    unmatched          = transactions.filter(reconcile_status='unmatched').count()

    failed_stmts = [
        {'file_name': s.file_name, 'error': s.parse_error or 'Unknown'}
        for s in statements.filter(parsed=False)
    ]
    failed_receipts = [
        {'file_name': r.file_name, 'error': r.extraction_error or 'Unknown'}
        for r in receipts.filter(extracted=False)
    ]

    return Response({
        'success': True,
        'summary': {
            'total_statements':    statements.count(),
            'parsed_statements':   statements.filter(parsed=True).count(),
            'failed_statements':   statements.filter(parsed=False).count(),
            'total_transactions':  transactions.count(),
            'total_receipts':      total_receipts,
            'extracted_receipts':  extracted_receipts,
            'receipts_with_amount': receipts.filter(extracted=True, amount__isnull=False).count(),
            'receipts_with_date':  receipts.filter(extracted=True, receipt_date__isnull=False).count(),
        },
        'reconciliation_status': {
            'matched':         matched,
            'receipt_missing': receipt_missing,
            'unmatched':       unmatched,
        },
        'failed_statements': failed_stmts,
        'failed_receipts':   failed_receipts,
        'is_complete': (
            statements.filter(parsed=False).count() == 0 and
            not failed_receipts and
            transactions.count() > 0
        ),
    })