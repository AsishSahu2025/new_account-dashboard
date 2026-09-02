from decimal import Decimal

from banklist.models import (
    TransactionGrantAllocation,
)


# def get_fund_available_amount(fund, bank_account):

#     allocations = (
#         TransactionFundAllocation.objects
#         .filter(
#             fund=fund,
#             transaction__bank_account=bank_account
#         )
#         .select_related('transaction')
#     )

#     available_amount = Decimal('0.00')

#     for allocation in allocations:

#         transaction = allocation.transaction
#         amount = allocation.amount

#         # ---------------------------------
#         # Money entering this bank
#         # ---------------------------------

#         if (
#             transaction.txn_type == 'credit'
#         ):
#             available_amount += amount

#         # ---------------------------------
#         # Money leaving this bank
#         # ---------------------------------

#         elif (
#             transaction.txn_type == 'debit'
#         ):
#             available_amount -= amount

#     return available_amount



from decimal import Decimal
from django.db.models import Sum


def get_grant_available_amount(grant, bank_account):
    """
    Calculate the amount currently available from a Grant
    for a specific Bank Account.

    Same business rule as the old Fund availability logic:
    - Grant must have source/credit allocation in this bank.
    - Debit allocations from the same Grant/bank reduce availability.
    """

    # -------------------------------------------------
    # Total amount received into this Grant
    # from credit transactions in this bank
    # -------------------------------------------------

    total_source_amount = (
        TransactionGrantAllocation.objects
        .filter(
            grant=grant,
            allocation_type='source',
            transaction__txn_type='credit',
            transaction__bank_account=bank_account
        )
        .aggregate(
            total=Sum('amount')
        )['total']
        or Decimal('0.00')
    )

    # -------------------------------------------------
    # Total amount already used by debit transactions
    # from this Grant in this bank
    # -------------------------------------------------

    total_destination_amount = (
        TransactionGrantAllocation.objects
        .filter(
            grant=grant,
            allocation_type='destination',
            transaction__txn_type='debit',
            transaction__bank_account=bank_account
        )
        .aggregate(
            total=Sum('amount')
        )['total']
        or Decimal('0.00')
    )

    # -------------------------------------------------
    # Available amount
    # -------------------------------------------------

    available_amount = (
        total_source_amount
        - total_destination_amount
    )

    if available_amount < Decimal('0.00'):
        available_amount = Decimal('0.00')

    return available_amount