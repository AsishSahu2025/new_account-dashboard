from rest_framework import serializers
from .models import Bank, BankAccount
from django.contrib.auth import authenticate
from .models import User, Company
from .models import Transaction, UploadedStatement, ReceiptDocument
from .models import (ReconciliationRun, ReconciliationRule, AuditLog, Particular, Grant, TransactionFundAllocation, Fund, GrantMaster, Agency, 
                    GrantMilestone,GrantTransaction)


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


class ReconciliationV2Serializer(serializers.Serializer):
    bank_account_1_id = serializers.IntegerField()
    bank_account_2_id = serializers.IntegerField()
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    auto_match = serializers.BooleanField(default=True)



# class TransactionManagementSerializer(serializers.ModelSerializer):
#     bank_name = serializers.CharField(
#         source="bank_account.bank.bank_name",
#         read_only=True
#     )

#     account_number = serializers.CharField(
#         source="bank_account.account_number",
#         read_only=True
#     )
#     source = serializers.SerializerMethodField()
#     destination = serializers.SerializerMethodField()
#     payment_to = serializers.SerializerMethodField()
#     transaction_type = serializers.SerializerMethodField()
#     receipt = serializers.SerializerMethodField()
#     receipt_exists = serializers.SerializerMethodField()
#     status = serializers.SerializerMethodField()
#     particular = serializers.SerializerMethodField()
#     accounting_particular = serializers.SerializerMethodField()
#     receipt_required = serializers.SerializerMethodField()

#     class Meta:
#         model = Transaction
#         fields = ["id","txn_date","value_date","description","ref_no","utr_no","bank_name","account_number",
#                   "payment_to","txn_type","transaction_type","amount","balance","status","particular","accounting_particular",
#                   "receipt_required","receipt_exists","receipt","created_at","source","destination"]

#     def get_payment_to(self, obj):
#         if obj.matched_txn:
#             if obj.matched_txn.bank_account:
#                 return obj.matched_txn.bank_account.bank.bank_name

#         return "-"

#     def get_source(self, obj):

#         if obj.txn_type == "debit":

#             return {
#                 "bank_name": obj.bank_account.bank.bank_name,
#                 "account_number": obj.bank_account.account_number,
#             }

#         return obj.description or "-"

#     def get_destination(self, obj):

#         if obj.txn_type == "credit":

#             return {
#                 "bank_name": obj.bank_account.bank.bank_name,
#                 "account_number": obj.bank_account.account_number,
#             }

#         return obj.description or "-"

#     def get_receipt_exists(self, obj):
#         return obj.matched_receipts.exists()

#     def get_receipt(self, obj):
#         receipt = obj.matched_receipts.first()
#         if receipt:
#             return {
#                 "id": receipt.id,
#                 "file_name": receipt.file_name,
#                 "file_link": receipt.file_link,
#             }

#         return None

#     def get_status(self, obj):
#         if obj.reconcile_status == "matched":
#             return "Matched"
#         if obj.reconcile_status == "receipt_missing":
#             return "Receipt Missing"
#         if obj.reconcile_status == "ignored":
#             return "Internal Transfer"

#         return "Unmatched"

#     def get_particular(self, obj):
#         if obj.particular:
#             return {
#                 "id": obj.particular.id,
#                 "name": obj.particular.name,
#             }

#         return None

#     def get_accounting_particular(self, obj):

#         if obj.accounting_particular:

#             return {
#                 "id": obj.accounting_particular.id,
#                 "name": obj.accounting_particular.name,
#             }

#         return None

#     def get_receipt_required(self, obj):
#         return (
#         obj.txn_type == "debit"
#         and obj.matched_txn is None
#     )


#     def get_transaction_type(self, obj):
#         if obj.txn_type == "credit":
#             return "Cash Inflow"

#         return "Cash Outflow"

from rest_framework import serializers

from .models import Transaction


from rest_framework import serializers


class TransactionManagementSerializer(
    serializers.ModelSerializer
):

    source = serializers.SerializerMethodField()
    destination = serializers.SerializerMethodField()

    transaction_type = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()

    closing_balance = serializers.SerializerMethodField()

    class Meta:

        model = Transaction

        fields = [
            "id",

            "txn_date",

            "source",

            "destination",

            "amount",

            "transaction_type",

            "closing_balance",

            "ref_no",

            "utr_no",

            "status",
        ]

    # =====================================================
    # Bank Information
    # =====================================================

    def get_bank_data(
        self,
        bank_account
    ):

        if not bank_account:

            return None

        bank_name = None

        if bank_account.bank:

            bank_name = (
                bank_account
                .bank
                .bank_name
            )

        return {

            "account_name": (
                bank_account.account_number
                if bank_account.account_number
                else None
            ),

            "bank_name": bank_name,

            "bank_id": (
                bank_account.id
            ),
        }

    # =====================================================
    # Check Internal Transfer
    # =====================================================

    def is_internal_transfer(
        self,
        obj
    ):

        return (

            obj.reconcile_status
            == "ignored"

            and

            obj.matched_txn
            is not None
        )

    # =====================================================
    # Get Internal Transfer Direction
    #
    # Always determine:
    #
    # Source Bank  → Destination Bank
    #
    # irrespective of whether current object is
    # debit or credit transaction.
    # =====================================================

    def get_internal_transfer_banks(
        self,
        obj
    ):

        if not obj.matched_txn:

            return (
                None,
                None
            )

        matched_transaction = (
            obj.matched_txn
        )

        # -------------------------------------------------
        # Current transaction is DEBIT
        #
        # Current Bank → Matched Bank
        # -------------------------------------------------

        if obj.txn_type == "debit":

            source_bank = (
                obj.bank_account
            )

            destination_bank = (
                matched_transaction
                .bank_account
            )

        # -------------------------------------------------
        # Current transaction is CREDIT
        #
        # Matched Bank → Current Bank
        # -------------------------------------------------

        elif obj.txn_type == "credit":

            source_bank = (
                matched_transaction
                .bank_account
            )

            destination_bank = (
                obj.bank_account
            )

        else:

            return (
                None,
                None
            )

        return (
            source_bank,
            destination_bank
        )

    # =====================================================
    # Source Chain
    #
    # Future ready structure.
    #
    # Direct:
    #
    # A1 → A2
    #
    # source = [A1]
    # destination = A2
    #
    # Future:
    #
    # A1 → A2 → A3
    #
    # source = [A1, A2]
    # destination = A3
    # =====================================================

    def get_source_chain(
        self,
        obj,
        source_bank,
        destination_bank
    ):

        source_chain = []

        # -------------------------------------------------
        # Add direct source bank
        # -------------------------------------------------

        if source_bank:

            source_chain.append(
                self.get_bank_data(
                    source_bank
                )
            )

        # -------------------------------------------------
        # IMPORTANT:
        #
        # Do not add destination bank to source chain.
        #
        # This prevents:
        #
        # source = [A1, A2]
        # destination = A2
        #
        # -------------------------------------------------

        if destination_bank:

            source_chain = [

                bank

                for bank in source_chain

                if (
                    bank["bank_id"]
                    != destination_bank.id
                )
            ]

        return source_chain

    # =====================================================
    # Source
    # =====================================================

    def get_source(
        self,
        obj
    ):

        # -------------------------------------------------
        # Internal Transfer
        # -------------------------------------------------

        if self.is_internal_transfer(
            obj
        ):

            (
                source_bank,
                destination_bank
            ) = (
                self.get_internal_transfer_banks(
                    obj
                )
            )

            return self.get_source_chain(

                obj,

                source_bank,

                destination_bank
            )

        # -------------------------------------------------
        # Normal Transaction
        # -------------------------------------------------

        return self.get_bank_data(
            obj.bank_account
        )

    # =====================================================
    # Destination
    # =====================================================

    def get_destination(
        self,
        obj
    ):

        # -------------------------------------------------
        # Normal transaction
        # -------------------------------------------------

        if not self.is_internal_transfer(
            obj
        ):

            return None

        # -------------------------------------------------
        # Internal Transfer
        # -------------------------------------------------

        (
            source_bank,
            destination_bank
        ) = (
            self.get_internal_transfer_banks(
                obj
            )
        )

        return self.get_bank_data(
            destination_bank
        )

    # =====================================================
    # Transaction Type
    # =====================================================

    def get_transaction_type(
        self,
        obj
    ):

        if obj.txn_type == "credit":
            return "Cash Inflow"

        if obj.txn_type == "debit":
            return "Cash Outflow"

        return obj.txn_type

    # =====================================================
    # Closing Balance
    #
    # Directly from Transaction.balance
    # =====================================================

    def get_closing_balance(
        self,
        obj
    ):

        if obj.balance is None:

            return None

        return str(
            obj.balance
        )

    # =====================================================
    # Status
    # =====================================================

    def get_status(
        self,
        obj
    ):

        if self.is_internal_transfer(
            obj
        ):

            return "Internal Transfer"

        if obj.reconcile_status == "matched":

            return "Matched"

        if (
            obj.reconcile_status
            == "receipt_missing"
        ):

            return "Receipt Missing"

        return "Unmatched"




class ParticularSerializer(serializers.ModelSerializer):

    class Meta:
        model = Particular
        fields = [
            "id",
            "name",
        ]


class TransactionUpdateSerializer(serializers.ModelSerializer):

    class Meta:
        model = Transaction
        fields = [                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         
            "particular",
            "accounting_particular",
        ]

    def validate_particular(self, value):

        if self.instance and value:
            if value.transaction_type.lower() != self.instance.txn_type.lower():
                raise serializers.ValidationError(
                    f"This Particular is only valid for {value.transaction_type} transactions."
                )

        return value
    # def validate(self, attrs):

    #     particular = attrs.get("particular")

    #     accounting_particular = attrs.get("accounting_particular")

    #     # If Particular is selected, Accounting Particular is mandatory
    #     if particular and not accounting_particular:
    #         raise serializers.ValidationError({
    #             "accounting_particular": "This field is required."
    #         })

    #     return attrs




from rest_framework import serializers
from .models import AccountingParticular


class AccountingParticularDropdownSerializer(serializers.ModelSerializer):

    class Meta:
        model = AccountingParticular
        fields = [
            "id",
            "name",
        ]



class TransactionJourneySerializer(serializers.ModelSerializer):

    transaction_type = serializers.SerializerMethodField()

    status = serializers.SerializerMethodField()

    particular = serializers.SerializerMethodField()

    accounting_particular = serializers.SerializerMethodField()

    source = serializers.SerializerMethodField()

    destination = serializers.SerializerMethodField()

    document = serializers.SerializerMethodField()
    matched = serializers.SerializerMethodField()

    completed = serializers.SerializerMethodField()

    class Meta:

        model = Transaction

        fields = [

            "id",

            "txn_date",

            "ref_no",

            "amount",

            "transaction_type",

            "status",

            "particular",

            "accounting_particular",

            "source",

            "destination",
            "matched",

            "completed",

            "document",

        ]

    def get_transaction_type(self, obj):

        if obj.txn_type == "credit":
            return "Cash Inflow"

        return "Cash Outflow"

    def get_status(self, obj):

        if obj.reconcile_status == "matched":
            return "Matched"

        if obj.reconcile_status == "receipt_missing":
            return "Receipt Missing"

        if obj.reconcile_status == "ignored":
            return "Internal Transfer"

        return "Unmatched"
    
    def get_particular(self, obj):

        if obj.particular:

            return {

                "id": obj.particular.id,

                "name": obj.particular.name,

            }

        return None

    def get_accounting_particular(self, obj):

        if obj.accounting_particular:

            return {

                "id": obj.accounting_particular.id,

                "name": obj.accounting_particular.name,

            }

        return None


    def get_source(self, obj):

        if obj.txn_type == "debit":

            return {

                "bank_name": obj.bank_account.bank.bank_name,

                "account_number": obj.bank_account.account_number,

            }

        return {

            "description": obj.description or "-"

        }

    def get_matched(self, obj):

        # Cash Inflow doesn't require matching
        if obj.txn_type == "credit":
            return None

        receipt = obj.matched_receipts.first()

        if not receipt:
            return None

        return {
            "date": receipt.created_at.date()
        }

    def get_completed(self, obj):

        # Cash Inflow doesn't require completion
        if obj.txn_type == "credit":
            return None

        receipt = obj.matched_receipts.first()

        if not receipt:
            return None

        return {
            "date": receipt.created_at.date()
        }


    def get_destination(self, obj):

        if obj.txn_type == "credit":

            return {

                "bank_name": obj.bank_account.bank.bank_name,

                "account_number": obj.bank_account.account_number,

            }

        return {

            "description": obj.description or "-"

        }


    def get_document(self, obj):

        # Cash Inflow doesn't require receipt
        if obj.txn_type == "credit":
            return None

        receipt = obj.matched_receipts.first()

        if not receipt:
            return None

        return {

            "id": receipt.id,

            "file_name": receipt.file_name,

            "file_link": receipt.file_link,

        }




class ListAgencySerializer(serializers.ModelSerializer):

    class Meta:
        model = Agency

        fields = [
            'id',
            'name',
            'short_name',
            # 'is_active',
            # 'created_at',
            # 'updated_at',
        ]

        read_only_fields = [
            'id',
            'created_at',
            'updated_at',
        ]


class CreateAgencySerializer(serializers.ModelSerializer):

    class Meta:
        model = Agency
        fields = [
            'id',
            'name',
            'short_name',
            'description',
            'is_active',
            'created_at',
            'updated_at',
        ]

        read_only_fields = [
            'id',
            'created_at',
            'updated_at',
        ]

    def validate_name(self, value):
        value = value.strip()

        if not value:
            raise serializers.ValidationError(
                'Agency name is required.'
            )

        return value

# class GrantSerializer(serializers.ModelSerializer):

#     grant_master_id = serializers.IntegerField(
#         write_only=True,
#         required=False,
#         allow_null=True
#     )

#     # grant_master_name = serializers.CharField(
#     #     write_only=True,
#     #     required=False,
#     #     allow_blank=True
#     # )

#     # grant_master_short_name = serializers.CharField(
#     #     write_only=True,
#     #     required=False,
#     #     allow_blank=True
#     # )

#     grant_master = GrantMasterSerializer(
#         read_only=True
#     )

#     class Meta:
#         model = Grant

#         fields = [
#             'id',
#             'grant_master',
#             'grant_master_id',
#             'name',
#             'description',
#             'is_active',
#             'created_at',
#             'updated_at',
#         ]

#         read_only_fields = [
#             'id',
#             'grant_master',
#             'created_at',
#             'updated_at',
#         ]




    # def validate(self, attrs):

    #     grant_master_id = attrs.get('grant_master_id')
    #     name = attrs.get('name', '').strip()

    #     if not name:
    #         raise serializers.ValidationError({
    #             'name': 'Grant name is required.'
    #         })

    #     if grant_master_id:
    #         try:
    #             GrantMaster.objects.get(
    #                 id=grant_master_id,
    #                 is_active=True
    #             )
    #         except GrantMaster.DoesNotExist:
    #             raise serializers.ValidationError({
    #                 'grant_master_id': 'Selected Grant Master does not exist.'
    #             })

    #     return attrs



class GrantSerializer(serializers.ModelSerializer):

    agency_id = serializers.PrimaryKeyRelatedField(
        source='agency',
        queryset=Agency.objects.filter(is_active=True),
        write_only=True
    )

    agency_name = serializers.CharField(
        source='agency.name',
        read_only=True
    )

    class Meta:
        model = Grant

        fields = [
            'id',
            'agency_id',
            'agency_name',
            'name',
            'amount',
            'status',
            'start_date',
            'end_date',
            'description',
            'is_active',
            'created_at',
            'updated_at',
        ]

        read_only_fields = [
            'id',
            'agency_name',
            'created_at',
            'updated_at',
        ]

    def validate(self, attrs):

        start_date = attrs.get('start_date')
        end_date = attrs.get('end_date')

        if start_date and end_date and start_date > end_date:
            raise serializers.ValidationError({
                'end_date':
                    'Grant end date cannot be earlier than start date.'
            })

        amount = attrs.get('amount')

        if amount is not None and amount <= 0:
            raise serializers.ValidationError({
                'amount':
                    'Grant amount must be greater than zero.'
            })

        return attrs  


class CreditGrantAllocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = TransactionFundAllocation
        fields = ['id','transaction','grant','amount','allocation_type','created_by','created_at',]
        read_only_fields = ['id','transaction','amount','allocation_type','created_by','created_at',]



class FundSerializer(serializers.ModelSerializer):
    grant_name = serializers.CharField(source='grant.name',read_only=True)

    class Meta:
        model = Fund
        fields = ['id','grant','grant_name','source_transaction','amount','created_at','updated_at',]
        read_only_fields = ['id','grant_name','source_transaction','amount','created_at','updated_at',]



class GrantListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Grant
        fields = ['id', 'name']



class GrantTransactionSerializer(serializers.ModelSerializer):

    class Meta:
        model = GrantTransaction

        fields = [
            'id',
            'transaction_name',
            'transaction_date',
            'amount',
            'document_information',
            'attachment',
            'created_at',
            'updated_at',
        ]

        read_only_fields = [
            'id',
            'created_at',
            'updated_at',
        ]

    def validate_amount(self, value):

        if value <= 0:
            raise serializers.ValidationError(
                'Transaction amount must be greater than zero.'
            )

        return value



class GrantMilestoneSerializer(serializers.ModelSerializer):

    class Meta:
        model = GrantMilestone

        fields = [
            'id',
            'name',
            'start_date',
            'end_date',
            'budget',
            'attachment',
            'created_at',
            'updated_at',
        ]

        read_only_fields = [
            'id',
            'created_at',
            'updated_at',
        ]

    def validate(self, attrs):

        start_date = attrs.get('start_date')
        end_date = attrs.get('end_date')

        if start_date and end_date and start_date > end_date:
            raise serializers.ValidationError({
                'end_date':
                    'Milestone end date cannot be earlier than start date.'
            })

        budget = attrs.get('budget')

        if budget is not None and budget <= 0:
            raise serializers.ValidationError({
                'budget':
                    'Milestone budget must be greater than zero.'
            })

        return attrs