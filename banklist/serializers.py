from rest_framework import serializers
from .models import Bank, BankAccount
from django.contrib.auth import authenticate
from .models import User, Company
from .models import Transaction, UploadedStatement, ReceiptDocument
from .models import ReconciliationRun, ReconciliationRule, AuditLog



class BankSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bank
        fields = '__all__'


class BankAccountSerializer(serializers.ModelSerializer):
    bank_name = serializers.CharField(source='bank.bank_name', read_only=True)
    bank_short_name = serializers.CharField(source='bank.short_name', read_only=True)

    class Meta:
        model = BankAccount
        fields = [
            'id', 'bank', 'bank_name', 'bank_short_name',
            'account_holder_name', 'account_number', 'ifsc_code',
            'bank_folder_id', 'statement_folder_id', 'drive_link',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['bank_folder_id', 'statement_folder_id', 'drive_link']


class RegisterSerializer(serializers.Serializer):
    company_name = serializers.CharField(max_length=255)
    full_name    = serializers.CharField(max_length=255)
    email        = serializers.EmailField()
    password     = serializers.CharField(min_length=8, write_only=True)
    confirm_password = serializers.CharField(min_length=8, write_only=True)

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('Email already registered')
        return value

    def validate(self, data):
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match'})
        return data

    def create(self, validated_data):
        company = Company.objects.create(name=validated_data['company_name'])
        user = User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            full_name=validated_data['full_name'],
            company=company,
        )
        return user


class LoginSerializer(serializers.Serializer):
    email    = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(username=data['email'], password=data['password'])
        if not user:
            raise serializers.ValidationError('Invalid email or password')
        if not user.is_active:
            raise serializers.ValidationError('Account is disabled')
        data['user'] = user
        return data

 
class TransactionSerializer(serializers.ModelSerializer):
    bank_name = serializers.SerializerMethodField()
 
    class Meta:
        model = Transaction
        fields = [
            'id', 'bank_account', 'bank_name', 'txn_date', 'value_date',
            'description', 'ref_no', 'utr_no',
            'txn_type', 'amount', 'balance',
            'reconcile_status', 'matched_txn',
            'created_at',
        ]
 
    def get_bank_name(self, obj):
        return obj.bank_account.bank.bank_name if obj.bank_account.bank else ''
 
 
class UploadedStatementSerializer(serializers.ModelSerializer):
    class Meta:
        model = UploadedStatement
        fields = [
            'id', 'bank_account', 'file_name', 'drive_file_id',
            'bank_detected', 'parsed', 'parse_error', 'uploaded_at',
        ]


class ReceiptDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReceiptDocument
        fields = [
            'id', 'drive_file_id', 'file_name', 'file_link', 'mime_type',
            'extracted', 'extraction_error', 'receipt_no', 'receipt_date',
            'amount', 'uploaded_at', 'created_at', 'updated_at',
        ]
 

# ============================================================
# Add this at the END of serializers.py
# ============================================================

class ReconciliationRunSerializer(serializers.ModelSerializer):
    bank_account_1_name = serializers.CharField(source='bank_account_1.bank.bank_name', read_only=True, allow_null=True)
    bank_account_2_name = serializers.CharField(source='bank_account_2.bank.bank_name', read_only=True, allow_null=True)
    run_by_email = serializers.CharField(source='run_by.email', read_only=True, allow_null=True)
    run_by_name = serializers.CharField(source='run_by.full_name', read_only=True, allow_null=True)
    
    class Meta:
        model = ReconciliationRun
        fields = [
            'id', 'company', 'bank_account_1', 'bank_account_1_name',
            'bank_account_2', 'bank_account_2_name', 'run_date',
            'total_transactions', 'matched_count', 'receipt_missing_count',
            'unmatched_count', 'ignored_count', 'match_percentage',
            'run_time_seconds', 'is_auto', 'run_by_email', 'run_by_name'
        ]


class ReconciliationRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReconciliationRule
        fields = '__all__'


class AuditLogSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True, allow_null=True)
    user_name = serializers.CharField(source='user.full_name', read_only=True, allow_null=True)
    
    class Meta:
        model = AuditLog
        fields = [
            'id', 'company', 'user', 'user_email', 'user_name',
            'action', 'entity_type', 'entity_id', 'details',
            'ip_address', 'timestamp'
        ]