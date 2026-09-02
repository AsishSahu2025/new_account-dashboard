# import calendar
# from datetime import date
# from collections import OrderedDict


# class CashFlowAnalysisService:

#     def __init__(self, company, month, year):
#         self.company = company
#         self.month = month
#         self.year = year

# def get_week_ranges(month, year):
#     """
#     Returns week ranges for the selected month.

#     Example:
#     [
#         {
#             "week": 1,
#             "start": date(2026,7,1),
#             "end": date(2026,7,7),
#             "label": "01 Jul - 07 Jul"
#         },
#         ...
#     ]
#     """

#     last_day = calendar.monthrange(year, month)[1]

#     ranges = []

#     start_day = 1
#     week = 1

#     while start_day <= last_day:

#         end_day = min(start_day + 6, last_day)

#         start_date = date(year, month, start_day)

#         end_date = date(year, month, end_day)

#         ranges.append(
#             {
#                 "week": week,
#                 "start": start_date,
#                 "end": end_date,
#                 "label": f"{start_date.strftime('%d %b')} - {end_date.strftime('%d %b')}",
#             }
#         )

#         start_day = end_day + 1

#         week += 1

#     return ranges



# def generate_cash_flow_report(queryset, week_ranges):
#     """
#     Generates week-wise cash flow grouped by Particular.

#     Returns:
#     [
#         {
#             "particular_id": 1,
#             "particular": "Grant Received",
#             "week_1": 50000,
#             "week_2": 0,
#             "week_3": 150000,
#             "week_4": 0,
#             "week_5": 450000,
#             "total": 650000,
#         }
#     ]
#     """

#     report = OrderedDict()

#     for transaction in queryset:

#         if transaction.particular is None:
#             continue

#         particular_id = transaction.particular.id

#         if particular_id not in report:

#             report[particular_id] = {
#                 "particular_id": particular_id,
#                 "particular": transaction.particular.name,
#                 "week_1": 0,
#                 "week_2": 0,
#                 "week_3": 0,
#                 "week_4": 0,
#                 "week_5": 0,
#                 "total": 0,
#             }

#         for week in week_ranges:

#             if week["start"] <= transaction.txn_date <= week["end"]:

#                 key = f"week_{week['week']}"

#                 report[particular_id][key] += float(transaction.amount)

#                 report[particular_id]["total"] += float(transaction.amount)

#                 break

#     return list(report.values())



# import calendar
# from datetime import date
# from banklist.models import Transaction, TransactionGrantAllocation
# from django.db.models import (
#     Sum,
#     Case,
#     When,
#     Value,
#     DecimalField,
# )
# from django.db.models.functions import Coalesce
# from django.db.models import F
# from decimal import Decimal


# class CashFlowAnalysisService:

#     def __init__(self, company, month, year, bank_account=None):

#         self.company = company
#         self.month = month
#         self.year = year
#         self.bank_account = bank_account

#         self.start_date = None
#         self.end_date = None
#         self._queryset = None
#         self.weeks = None

#     # ---------------------------------------------------------
#     # Validate Request
#     # ---------------------------------------------------------

#     def validate(self):

#         if self.month is None or self.year is None:
#             raise ValueError("Month and Year are required.")

#         try:
#             self.month = int(self.month)
#             self.year = int(self.year)

#         except Exception:
#             raise ValueError("Invalid Month or Year.")

#         if self.month < 1 or self.month > 12:
#             raise ValueError("Month must be between 1 and 12.")

#         last_day = calendar.monthrange(
#             self.year,
#             self.month
#         )[1]

#         self.start_date = date(
#             self.year,
#             self.month,
#             1
#         )

#         self.end_date = date(
#             self.year,
#             self.month,
#             last_day
#         )
#         self.weeks = self.get_week_ranges()

#     # ---------------------------------------------------------
#     # Base Queryset
#     # ---------------------------------------------------------

#     def get_queryset(self):

#         if self._queryset is not None:
#             return self._queryset

#         queryset = (
#             Transaction.objects
#             .filter(
#                 company=self.company,
#                 txn_date__range=[
#                     self.start_date,
#                     self.end_date,
#                 ],
#             )
#             .select_related(
#                 "particular",
#                 "bank_account",
#                 "bank_account__bank",
#             )
#         )

#         if self.bank_account:

#             queryset = queryset.filter(
#                 bank_account_id=self.bank_account
#             )

#         self._queryset = queryset

#         return self._queryset

#     # ---------------------------------------------------------
#     # Week Ranges
#     # ---------------------------------------------------------

#     def get_week_ranges(self):

#         last_day = calendar.monthrange(
#             self.year,
#             self.month
#         )[1]

#         week_ranges = []

#         start_day = 1
#         week = 1

#         while start_day <= last_day:

#             end_day = min(
#                 start_day + 6,
#                 last_day
#             )

#             start = date(
#                 self.year,
#                 self.month,
#                 start_day
#             )

#             end = date(
#                 self.year,
#                 self.month,
#                 end_day
#             )

#             week_ranges.append(
#                 {
#                     "week": week,
#                     "start": start,
#                     "end": end,
#                     "label": f"{start.strftime('%d %b')} - {end.strftime('%d %b')}"
#                 }
#             )

#             week += 1

#             start_day = end_day + 1

#         return week_ranges

#     # ---------------------------------------------------------
#     # Report Builder
#     # ---------------------------------------------------------

#     def build_report(self, txn_type):

#         queryset = (
#             self.get_queryset()
#             .filter(
#                 txn_type=txn_type,
#                 particular__isnull=False,
#             )
#         )

#         week_ranges = self.weeks

#         annotations = {}

#         for week in week_ranges:

#             annotations[f"week_{week['week']}"] = Coalesce(
#                 Sum(
#                     Case(
#                         When(
#                             txn_date__range=[week["start"], week["end"]],
#                             then=F("amount"),
#                         ),
#                         default=Value(
#                             0,
#                             output_field=DecimalField(
#                                 max_digits=15,
#                                 decimal_places=2,
#                             ),
#                         ),
#                         output_field=DecimalField(
#                             max_digits=15,
#                             decimal_places=2,
#                         ),
#                     )
#                 ),
#                 Value(
#                     0,
#                     output_field=DecimalField(
#                         max_digits=15,
#                         decimal_places=2,
#                     ),
#                 ),
#             )

#         report = (
#             queryset
#             .values(
#                 "particular",
#                 "particular__name",
#             )
#             .annotate(
#                 **annotations,
#                 total=Coalesce(
#                     Sum("amount"),
#                     Value(
#                         0,
#                         output_field=DecimalField(
#                             max_digits=15,
#                             decimal_places=2,
#                         ),
#                     ),
#                 )
#             )
#             .order_by(
#                 "particular__name"
#             )
#         )

#         results = []

#         for row in report:

#             item = {
#                 "particular_id": row["particular"],
#                 "particular": row["particular__name"],
#             }

#             for week in week_ranges:

#                 item[f"week_{week['week']}"] = float(
#                     row[f"week_{week['week']}"]
#                 )

#             item["total"] = float(row["total"])

#             results.append(item)

#         return results


#     def calculate_summary(
#     self,
#     inflow,
#     outflow,
# ):

#         total_inflow = sum(
#             row["total"]
#             for row in inflow
#         )

#         total_outflow = sum(
#             row["total"]
#             for row in outflow
#         )

#         return {

#             "total_inflow": float(total_inflow),

#             "total_outflow": float(total_outflow),

#             "net_cash_flow": float(total_inflow - total_outflow),

#         }

#     def calculate_week_totals(
#     self,
#     report,
# ):

#         week_totals = {}

#         for week in self.weeks:

#             key = f"week_{week['week']}"

#             week_totals[key] = sum(
#                 row[key]
#                 for row in report
#             )

#         week_totals["total"] = sum(
#             row["total"]
#             for row in report
#         )

#         return week_totals
#     # ---------------------------------------------------------
#     # Execute
#     # ---------------------------------------------------------

#     def execute(self):

#         self.validate()

#         weeks = self.weeks

#         cash_inflow = self.build_report(
#         "credit"
#     )

#         cash_outflow = self.build_report(
#             "debit"
#         )

#         cash_inflow_totals = self.calculate_week_totals(
#             cash_inflow
#         )

#         cash_outflow_totals = self.calculate_week_totals(
#             cash_outflow
#         )

#         summary = self.calculate_summary(
#             cash_inflow,
#             cash_outflow,
#         )

#         return {

#         "success": True,

#         "month": self.month,

#         "year": self.year,

#         "weeks": [
#             {
#                 "week": week["week"],
#                 "label": week["label"],
#             }
#             for week in weeks
#         ],

#         "summary": summary,

#         "cash_inflow": {
#             "rows": cash_inflow,
#             "totals": cash_inflow_totals,
#         },

#         "cash_outflow": {
#             "rows": cash_outflow,
#             "totals": cash_outflow_totals,
#         },

#     }




import calendar

from datetime import date

from django.db.models import (
    Sum,
    Case,
    When,
    F,
    Value,
    DecimalField,
)

from django.db.models.functions import Coalesce

from banklist.models import (
    Transaction,
    TransactionGrantAllocation,
)


class CashFlowAnalysisService:

    def __init__(
        self,
        company,
        month,
        year,
        bank_account=None
    ):

        self.company = company
        self.month = month
        self.year = year
        self.bank_account = bank_account

        self.start_date = None
        self.end_date = None
        self._queryset = None
        self.weeks = None


    # ---------------------------------------------------------
    # Validate Request
    # ---------------------------------------------------------

    def validate(self):

        if self.month is None or self.year is None:

            raise ValueError(
                "Month and Year are required."
            )

        try:

            self.month = int(
                self.month
            )

            self.year = int(
                self.year
            )

        except Exception:

            raise ValueError(
                "Invalid Month or Year."
            )

        if self.month < 1 or self.month > 12:

            raise ValueError(
                "Month must be between 1 and 12."
            )

        last_day = calendar.monthrange(
            self.year,
            self.month
        )[1]

        self.start_date = date(
            self.year,
            self.month,
            1
        )

        self.end_date = date(
            self.year,
            self.month,
            last_day
        )

        self.weeks = self.get_week_ranges()


    # ---------------------------------------------------------
    # Base Transaction Queryset
    # ---------------------------------------------------------

    def get_queryset(self):

        if self._queryset is not None:

            return self._queryset

        queryset = (
            Transaction.objects
            .filter(
                company=self.company,
                txn_date__range=[
                    self.start_date,
                    self.end_date,
                ],
            )
            .select_related(
                "particular",
                "bank_account",
                "bank_account__bank",
            )
        )

        # -------------------------------------------------
        # Optional Bank Filter
        # -------------------------------------------------

        if self.bank_account:

            queryset = queryset.filter(
                bank_account_id=self.bank_account
            )

        self._queryset = queryset

        return self._queryset


    # ---------------------------------------------------------
    # Week Ranges
    # ---------------------------------------------------------

    def get_week_ranges(self):

        last_day = calendar.monthrange(
            self.year,
            self.month
        )[1]

        week_ranges = []

        start_day = 1
        week = 1

        while start_day <= last_day:

            end_day = min(
                start_day + 6,
                last_day
            )

            start = date(
                self.year,
                self.month,
                start_day
            )

            end = date(
                self.year,
                self.month,
                end_day
            )

            week_ranges.append(
                {
                    "week": week,

                    "start": start,

                    "end": end,

                    "label": (
                        f"{start.strftime('%d %b')} - "
                        f"{end.strftime('%d %b')}"
                    ),
                }
            )

            week += 1

            start_day = end_day + 1

        return week_ranges


    # =========================================================
    # GRANT-WISE CASH INFLOW
    #
    # Only credit transactions that are actually assigned
    # to a Grant through TransactionGrantAllocation.
    #
    # Returns ONE row called "Grant".
    # =========================================================

    def build_grant_inflow_report(self):

        queryset = (
            TransactionGrantAllocation.objects
            .filter(
                grant__company=self.company,

                transaction__txn_type="credit",

                transaction__txn_date__range=[
                    self.start_date,
                    self.end_date,
                ],

                allocation_type="source",
            )
        )

        # -------------------------------------------------
        # Optional Bank Filter
        # -------------------------------------------------

        if self.bank_account:

            queryset = queryset.filter(
                transaction__bank_account_id=self.bank_account
            )

        # -------------------------------------------------
        # Week-wise annotations
        # -------------------------------------------------

        annotations = {}

        for week in self.weeks:

            week_key = (
                f"week_{week['week']}"
            )

            annotations[week_key] = Coalesce(

                Sum(
                    Case(

                        When(
                            transaction__txn_date__range=[
                                week["start"],
                                week["end"],
                            ],
                            then=F("amount"),
                        ),

                        default=Value(
                            0,
                            output_field=DecimalField(
                                max_digits=15,
                                decimal_places=2,
                            ),
                        ),

                        output_field=DecimalField(
                            max_digits=15,
                            decimal_places=2,
                        ),
                    )
                ),

                Value(
                    0,
                    output_field=DecimalField(
                        max_digits=15,
                        decimal_places=2,
                    ),
                ),
            )

        # -------------------------------------------------
        # Calculate all assigned Grant credits together
        #
        # We do not show individual Grant names.
        # We show only one row: Grant.
        # -------------------------------------------------

        report = queryset.aggregate(

            **annotations,

            total=Coalesce(

                Sum("amount"),

                Value(
                    0,
                    output_field=DecimalField(
                        max_digits=15,
                        decimal_places=2,
                    ),
                ),
            )
        )

        # -------------------------------------------------
        # If there are no assigned Grant credits
        # -------------------------------------------------

        total_amount = report.get(
            "total"
        ) or 0

        if total_amount == 0:

            return []


        # -------------------------------------------------
        # Build one global Grant row
        # -------------------------------------------------

        grant_row = {

            "particular_id": None,

            "particular": "Grant Received",
        }

        for week in self.weeks:

            week_key = (
                f"week_{week['week']}"
            )

            grant_row[week_key] = float(
                report.get(week_key) or 0
            )

        grant_row["total"] = float(
            total_amount
        )

        return [
            grant_row
        ]


    # =========================================================
    # NORMAL PARTICULAR-WISE REPORT
    #
    # Used for Cash Outflow / Debit Transactions
    # =========================================================

    def build_report(
        self,
        txn_type
    ):

        queryset = (
            self.get_queryset()
            .filter(
                txn_type=txn_type,
                particular__isnull=False,
            )
        )

        annotations = {}

        # -------------------------------------------------
        # Week calculations
        # -------------------------------------------------

        for week in self.weeks:

            week_key = (
                f"week_{week['week']}"
            )

            annotations[week_key] = Coalesce(

                Sum(
                    Case(

                        When(
                            txn_date__range=[
                                week["start"],
                                week["end"],
                            ],
                            then=F("amount"),
                        ),

                        default=Value(
                            0,
                            output_field=DecimalField(
                                max_digits=15,
                                decimal_places=2,
                            ),
                        ),

                        output_field=DecimalField(
                            max_digits=15,
                            decimal_places=2,
                        ),
                    )
                ),

                Value(
                    0,
                    output_field=DecimalField(
                        max_digits=15,
                        decimal_places=2,
                    ),
                ),
            )

        # -------------------------------------------------
        # Group by Particular
        # -------------------------------------------------

        report = (

            queryset

            .values(
                "particular",
                "particular__name",
            )

            .annotate(

                **annotations,

                total=Coalesce(

                    Sum("amount"),

                    Value(
                        0,
                        output_field=DecimalField(
                            max_digits=15,
                            decimal_places=2,
                        ),
                    ),
                )
            )

            .order_by(
                "particular__name"
            )
        )

        results = []

        # -------------------------------------------------
        # Build response rows
        # -------------------------------------------------

        for row in report:

            item = {

                "particular_id": (
                    row["particular"]
                ),

                "particular": (
                    row["particular__name"]
                ),
            }

            for week in self.weeks:

                week_key = (
                    f"week_{week['week']}"
                )

                item[week_key] = float(
                    row[week_key] or 0
                )

            item["total"] = float(
                row["total"] or 0
            )

            results.append(
                item
            )

        return results


    # ---------------------------------------------------------
    # Calculate Summary
    # ---------------------------------------------------------

    def calculate_summary(
        self,
        inflow,
        outflow,
    ):

        total_inflow = sum(

            row["total"]

            for row in inflow
        )

        total_outflow = sum(

            row["total"]

            for row in outflow
        )

        return {

            "total_inflow": float(
                total_inflow
            ),

            "total_outflow": float(
                total_outflow
            ),

            "net_cash_flow": float(
                total_inflow
                -
                total_outflow
            ),
        }


    # ---------------------------------------------------------
    # Calculate Week Totals
    # ---------------------------------------------------------

    def calculate_week_totals(
        self,
        report,
    ):

        week_totals = {}

        for week in self.weeks:

            week_key = (
                f"week_{week['week']}"
            )

            week_totals[week_key] = sum(

                row.get(
                    week_key,
                    0
                )

                for row in report
            )

        week_totals["total"] = sum(

            row.get(
                "total",
                0
            )

            for row in report
        )

        return week_totals


    # =========================================================
    # Execute
    # =========================================================

    def execute(self):

        # -------------------------------------------------
        # Validate Month and Year
        # -------------------------------------------------

        self.validate()

        weeks = self.weeks


        # -------------------------------------------------
        # CASH INFLOW
        #
        # Only assigned Grant credit transactions
        # -------------------------------------------------

        cash_inflow = (
            self.build_grant_inflow_report()
        )


        # -------------------------------------------------
        # CASH OUTFLOW
        #
        # Debit transactions grouped by Particular
        # -------------------------------------------------

        cash_outflow = (
            self.build_report(
                "debit"
            )
        )


        # -------------------------------------------------
        # Calculate Inflow Totals
        # -------------------------------------------------

        cash_inflow_totals = (
            self.calculate_week_totals(
                cash_inflow
            )
        )


        # -------------------------------------------------
        # Calculate Outflow Totals
        # -------------------------------------------------

        cash_outflow_totals = (
            self.calculate_week_totals(
                cash_outflow
            )
        )


        # -------------------------------------------------
        # Calculate Summary
        # -------------------------------------------------

        summary = (
            self.calculate_summary(
                cash_inflow,
                cash_outflow,
            )
        )


        # -------------------------------------------------
        # Final Response
        # -------------------------------------------------

        return {

            "success": True,

            "month": self.month,

            "year": self.year,

            "weeks": [

                {
                    "week": week["week"],

                    "label": week["label"],
                }

                for week in weeks
            ],


            "summary": summary,


            # -------------------------------------------------
            # Cash Inflow
            # -------------------------------------------------

            "cash_inflow": {

                "rows": (
                    cash_inflow
                ),

                "totals": (
                    cash_inflow_totals
                ),
            },


            # -------------------------------------------------
            # Cash Outflow
            # -------------------------------------------------

            "cash_outflow": {

                "rows": (
                    cash_outflow
                ),

                "totals": (
                    cash_outflow_totals
                ),
            },
        }

    


import calendar

from datetime import date
from decimal import Decimal

from django.db.models import Sum

from banklist.models import (
    TransactionGrantAllocation,
    Grant,
)


# class GrantWiseOutflowService:

#     def __init__(
#         self,
#         company,
#         month,
#         year,
#         bank_account=None,
#         grant_id=None
#     ):
#         self.company = company
#         self.month = month
#         self.year = year
#         self.bank_account = bank_account
#         self.grant_id = grant_id

#         self.start_date = None
#         self.end_date = None
#         self.weeks = None

#     # =========================================================
#     # Validation
#     # =========================================================

#     def validate(self):

#         if self.month is None or self.year is None:
#             raise ValueError(
#                 "Month and Year are required."
#             )

#         try:
#             self.month = int(self.month)
#             self.year = int(self.year)
#         except (TypeError, ValueError):
#             raise ValueError(
#                 "Invalid Month or Year."
#             )

#         if self.month < 1 or self.month > 12:
#             raise ValueError(
#                 "Month must be between 1 and 12."
#             )

#         if self.year < 1:
#             raise ValueError(
#                 "Invalid Year."
#             )

#         last_day = calendar.monthrange(
#             self.year,
#             self.month
#         )[1]

#         self.start_date = date(
#             self.year,
#             self.month,
#             1
#         )

#         self.end_date = date(
#             self.year,
#             self.month,
#             last_day
#         )

#         self.weeks = self.get_week_ranges()

#     # =========================================================
#     # Week Ranges
#     # =========================================================

#     def get_week_ranges(self):

#         last_day = calendar.monthrange(
#             self.year,
#             self.month
#         )[1]

#         week_ranges = []

#         start_day = 1
#         week_number = 1

#         while start_day <= last_day:

#             end_day = min(
#                 start_day + 6,
#                 last_day
#             )

#             start = date(
#                 self.year,
#                 self.month,
#                 start_day
#             )

#             end = date(
#                 self.year,
#                 self.month,
#                 end_day
#             )

#             week_ranges.append(
#                 {
#                     "week": week_number,
#                     "start": start,
#                     "end": end,
#                     "label": (
#                         f"{start.strftime('%d %b')} - "
#                         f"{end.strftime('%d %b')}"
#                     )
#                 }
#             )

#             week_number += 1
#             start_day = end_day + 1

#         return week_ranges

#     # =========================================================
#     # GLOBAL SUMMARY
#     # =========================================================

#     def get_global_summary(self):

#     # =====================================================
#     # No bank selected
#     # =====================================================

#         if not self.bank_account:

#             return {
#                 'total_grant_amount': None,
#                 'total_outflow': None,
#                 'total_remaining': None,
#             }

#         # =====================================================
#         # Bank selected
#         # =====================================================

#         grant_filter = {
#             'company': self.company,
#             'is_active': True,
#         }

#         if self.grant_id:
#             grant_filter['id'] = self.grant_id

#         # -----------------------------------------------------
#         # Total Grant Amount
#         # -----------------------------------------------------

#         total_grant_amount = (
#             Grant.objects
#             .filter(**grant_filter)
#             .aggregate(
#                 total=Sum('amount')
#             )['total']
#             or Decimal('0.00')
#         )

#         # -----------------------------------------------------
#         # Total Historical Outflow
#         # -----------------------------------------------------

#         allocation_filter = {
#             'grant__company': self.company,
#             'grant__is_active': True,

#             'allocation_type': 'destination',

#             'transaction__company': self.company,

#             'transaction__txn_type': 'debit',

#             'transaction__bank_account_id': (
#                 self.bank_account
#             ),
#         }

#         if self.grant_id:
#             allocation_filter[
#                 'grant_id'
#             ] = self.grant_id

#         total_outflow = (
#             TransactionGrantAllocation.objects
#             .filter(**allocation_filter)
#             .aggregate(
#                 total=Sum('amount')
#             )['total']
#             or Decimal('0.00')
#         )

#         # -----------------------------------------------------
#         # Remaining
#         # -----------------------------------------------------

#         total_remaining = (
#             total_grant_amount
#             - total_outflow
#         )

#         if total_remaining < Decimal('0.00'):
#             total_remaining = Decimal('0.00')

#         return {
#             'total_grant_amount': str(
#                 total_grant_amount
#             ),

#             'total_outflow': str(
#                 total_outflow
#             ),

#             'total_remaining': str(
#                 total_remaining
#             ),
#         }
#     # =========================================================
#     # MONTHLY ALLOCATIONS
#     # =========================================================

#     def get_monthly_allocations(self):

#         queryset = (
#             TransactionGrantAllocation.objects
#             .filter(
#                 transaction__company=self.company,

#                 transaction__txn_type='debit',

#                 transaction__txn_date__range=[
#                     self.start_date,
#                     self.end_date,
#                 ],

#                 allocation_type='destination',

#                 grant__company=self.company,

#                 grant__is_active=True,
#             )
#             .select_related(
#                 'transaction',
#                 'transaction__particular',
#                 'grant',
#                 'grant__agency',
#             )
#             .order_by(
#                 'grant__agency__name',
#                 'grant__name',
#                 'transaction__particular__name',
#             )
#         )

#         if self.bank_account:
#             queryset = queryset.filter(
#                 transaction__bank_account_id=(
#                     self.bank_account
#                 )
#             )

#         if self.grant_id:
#             queryset = queryset.filter(
#                 grant_id=self.grant_id
#             )

#         return queryset

#     # =========================================================
#     # MONTHLY REPORT
#     # =========================================================

#     def build_monthly_report(self):

#         allocations = self.get_monthly_allocations()

#         grant_data = {}

#         for allocation in allocations:

#             grant = allocation.grant
#             txn = allocation.transaction
#             particular = txn.particular

#             # -------------------------------------------------
#             # Grant
#             # -------------------------------------------------

#             if grant.id not in grant_data:

#                 grant_data[grant.id] = {

#                     'grant_id': grant.id,

#                     'grant_name': grant.name,

#                     'agency_id': (
#                         grant.agency.id
#                         if grant.agency
#                         else None
#                     ),

#                     'agency_name': (
#                         grant.agency.name
#                         if grant.agency
#                         else None
#                     ),

#                     'grant_amount': (
#                         grant.amount
#                         or Decimal('0.00')
#                     ),

#                     'monthly_outflow': (
#                         Decimal('0.00')
#                     ),

#                     'particulars': {},
#                 }

#             grant_data[
#                 grant.id
#             ]['monthly_outflow'] += allocation.amount

#             # -------------------------------------------------
#             # Particular
#             # -------------------------------------------------

#             if particular:

#                 particular_id = particular.id
#                 particular_name = particular.name

#             else:

#                 particular_id = None
#                 particular_name = 'Uncategorized'

#             particular_key = (
#                 particular_id
#                 if particular_id is not None
#                 else 'uncategorized'
#             )

#             if particular_key not in grant_data[
#                 grant.id
#             ]['particulars']:

#                 grant_data[
#                     grant.id
#                 ]['particulars'][particular_key] = {

#                     'particular_id': particular_id,

#                     'particular_name': (
#                         particular_name
#                     ),

#                     'weekly_amounts': {
#                         f'week_{week["week"]}':
#                             Decimal('0.00')
#                         for week in self.weeks
#                     },

#                     'total': Decimal('0.00'),
#                 }

#             # -------------------------------------------------
#             # Week
#             # -------------------------------------------------

#             for week in self.weeks:

#                 if (
#                     week['start']
#                     <= txn.txn_date
#                     <= week['end']
#                 ):

#                     week_key = (
#                         f"week_{week['week']}"
#                     )

#                     particular_data = (
#                         grant_data[
#                             grant.id
#                         ]['particulars'][
#                             particular_key
#                         ]
#                     )

#                     particular_data[
#                         'weekly_amounts'
#                     ][week_key] += allocation.amount

#                     particular_data[
#                         'total'
#                     ] += allocation.amount

#                     break

#         # =====================================================
#         # Build final rows
#         # =====================================================

#         results = []

#         for data in grant_data.values():

#             particular_rows = []

#             for particular_data in (
#                 data['particulars'].values()
#             ):

#                 particular_item = {

#                     'particular_id': (
#                         particular_data[
#                             'particular_id'
#                         ]
#                     ),

#                     'particular_name': (
#                         particular_data[
#                             'particular_name'
#                         ]
#                     ),

#                     'total': float(
#                         particular_data['total']
#                     ),
#                 }

#                 for week in self.weeks:

#                     key = (
#                         f"week_{week['week']}"
#                     )

#                     particular_item[key] = float(
#                         particular_data[
#                             'weekly_amounts'
#                         ][key]
#                     )

#                 particular_rows.append(
#                     particular_item
#                 )

#             # -------------------------------------------------
#             # Grant row
#             #
#             # Remaining comes from GLOBAL summary later.
#             # We do not calculate it with a query per Grant.
#             # -------------------------------------------------

#             results.append(
#                 {
#                     'grant_id': data['grant_id'],

#                     'grant_name': data['grant_name'],

#                     'agency_id': data['agency_id'],

#                     'agency_name': data['agency_name'],

#                     'grant_amount': str(
#                         data['grant_amount']
#                     ),

#                     'total_outflow': str(
#                         data['monthly_outflow']
#                     ),

#                     'particulars': (
#                         particular_rows
#                     ),
#                 }
#             )

#         return results

#     # =========================================================
#     # Weekly Totals
#     # =========================================================

#     def calculate_week_totals(self, report):

#         week_totals = {}

#         for week in self.weeks:

#             key = f"week_{week['week']}"

#             total = Decimal('0.00')

#             for grant in report:

#                 for particular in (
#                     grant['particulars']
#                 ):

#                     total += Decimal(
#                         str(
#                             particular[key]
#                         )
#                     )

#             week_totals[key] = float(total)

#         # -----------------------------------------------------
#         # Selected month's total
#         # -----------------------------------------------------

#         week_totals['total'] = float(
#             sum(
#                 Decimal(
#                     grant['total_outflow']
#                 )
#                 for grant in report
#             )
#         )

#         return week_totals

#     # =========================================================
#     # Execute
#     # =========================================================

#     def execute(self):

#         self.validate()

#         # -----------------------------------------------------
#         # GLOBAL SUMMARY
#         # -----------------------------------------------------

#         summary = self.get_global_summary()

#         # -----------------------------------------------------
#         # MONTHLY REPORT
#         # -----------------------------------------------------

#         report = self.build_monthly_report()

#         # -----------------------------------------------------
#         # MONTHLY WEEK TOTALS
#         # -----------------------------------------------------

#         week_totals = (
#             self.calculate_week_totals(
#                 report
#             )
#         )

#         return {

#             'success': True,

#             'month': self.month,

#             'year': self.year,

#             'bank_account_id': (
#                 int(self.bank_account)
#                 if self.bank_account
#                 else None
#             ),

#             'grant_id': (
#                 int(self.grant_id)
#                 if self.grant_id
#                 else None
#             ),

#             'weeks': [
#                 {
#                     'week': week['week'],
#                     'label': week['label'],
#                 }
#                 for week in self.weeks
#             ],

#             # =================================================
#             # GLOBAL SUMMARY
#             # =================================================

#             'summary': summary,

#             # =================================================
#             # MONTHLY GRANT REPORT
#             # =================================================

#             'grant_wise_outflow': {

#                 'rows': report,

#                 'totals': week_totals,

#             },
#         }




# import calendar

# from datetime import date
# from decimal import Decimal

# from django.db.models import Sum

# from banklist.models import (
#     Grant,
#     TransactionGrantAllocation,
# )


# class GrantWiseOutflowService:
#     """
#     Generate Grant-wise outflow report for:

#         Bank -> Grant -> Particular -> Week

#     Business Rules
#     --------------

#     1. Bank and Grant are both required.

#     2. Grant must belong to the user's company.

#     3. Grant must be assigned to the selected Bank through
#        a source/credit allocation.

#     4. Monthly outflow:
#        - Transaction type = debit
#        - Allocation type = destination
#        - Selected Bank
#        - Selected Grant
#        - Selected Month

#     5. Grant amount:
#        - Always the complete Grant.amount.
#        - Not month based.

#     6. Historical outflow:
#        - All debit/destination allocations
#        - Selected Bank
#        - Selected Grant
#        - No month restriction.

#     7. Remaining amount:
#        Grant.amount - historical outflow
#     """

#     def __init__(
#         self,
#         company,
#         month,
#         year,
#         bank_account,
#         grant_id
#     ):

#         self.company = company
#         self.month = month
#         self.year = year
#         self.bank_account = bank_account
#         self.grant_id = grant_id

#         self.start_date = None
#         self.end_date = None
#         self.weeks = None

#     # =========================================================
#     # 1. Validate Request
#     # =========================================================

#     def validate(self):

#         if self.month is None:
#             raise ValueError(
#                 "Month is required."
#             )

#         if self.year is None:
#             raise ValueError(
#                 "Year is required."
#             )

#         if self.bank_account is None:
#             raise ValueError(
#                 "bank_account_id is required."
#             )

#         if self.grant_id is None:
#             raise ValueError(
#                 "grant_id is required."
#             )

#         try:

#             self.month = int(self.month)

#         except (TypeError, ValueError):

#             raise ValueError(
#                 "Invalid month."
#             )

#         try:

#             self.year = int(self.year)

#         except (TypeError, ValueError):

#             raise ValueError(
#                 "Invalid year."
#             )

#         try:

#             self.bank_account = int(
#                 self.bank_account
#             )

#         except (TypeError, ValueError):

#             raise ValueError(
#                 "Invalid bank_account_id."
#             )

#         try:

#             self.grant_id = int(
#                 self.grant_id
#             )

#         except (TypeError, ValueError):

#             raise ValueError(
#                 "Invalid grant_id."
#             )

#         if self.month < 1 or self.month > 12:

#             raise ValueError(
#                 "Month must be between 1 and 12."
#             )

#         if self.year < 1:

#             raise ValueError(
#                 "Invalid year."
#             )

#         # -----------------------------------------------------
#         # Month dates
#         # -----------------------------------------------------

#         last_day = calendar.monthrange(
#             self.year,
#             self.month
#         )[1]

#         self.start_date = date(
#             self.year,
#             self.month,
#             1
#         )

#         self.end_date = date(
#             self.year,
#             self.month,
#             last_day
#         )

#         self.weeks = self.get_week_ranges()

#     # =========================================================
#     # 2. Week Ranges
#     # =========================================================

#     def get_week_ranges(self):

#         last_day = calendar.monthrange(
#             self.year,
#             self.month
#         )[1]

#         week_ranges = []

#         start_day = 1
#         week_number = 1

#         while start_day <= last_day:

#             end_day = min(
#                 start_day + 6,
#                 last_day
#             )

#             start = date(
#                 self.year,
#                 self.month,
#                 start_day
#             )

#             end = date(
#                 self.year,
#                 self.month,
#                 end_day
#             )

#             week_ranges.append(
#                 {
#                     "week": week_number,

#                     "start": start,

#                     "end": end,

#                     "label": (
#                         f"{start.strftime('%d %b')} - "
#                         f"{end.strftime('%d %b')}"
#                     ),
#                 }
#             )

#             week_number += 1

#             start_day = end_day + 1

#         return week_ranges

#     # =========================================================
#     # 3. Get Grant
#     # =========================================================

#     def get_grant(self):

#         try:

#             grant = (
#                 Grant.objects
#                 .select_related(
#                     'agency'
#                 )
#                 .get(
#                     id=self.grant_id,
#                     company=self.company,
#                     is_active=True
#                 )
#             )

#         except Grant.DoesNotExist:

#             raise ValueError(
#                 "Grant not found or inactive."
#             )

#         return grant

#     # =========================================================
#     # 4. Validate Grant -> Bank Assignment
#     #
#     # A Grant is considered assigned to a Bank when there is
#     # a SOURCE allocation from a CREDIT transaction.
#     #
#     # This is the same assignment logic we use for the
#     # Grant receiving money from the Bank.
#     # =========================================================

#     def validate_bank_grant_relation(self):

#         exists = (
#             TransactionGrantAllocation.objects
#             .filter(
#                 grant_id=self.grant_id,

#                 grant__company=self.company,

#                 grant__is_active=True,

#                 transaction__company=self.company,

#                 transaction__bank_account_id=(
#                     self.bank_account
#                 ),

#                 transaction__txn_type='credit',

#                 allocation_type='source',
#             )
#             .exists()
#         )

#         if not exists:

#             raise ValueError(
#                 "Selected Grant is not assigned "
#                 "to the selected Bank."
#             )

#     # =========================================================
#     # 5. Get Monthly Debit Allocations
#     # =========================================================

#     def get_monthly_allocations(self):

#         return (
#             TransactionGrantAllocation.objects
#             .filter(
#                 grant_id=self.grant_id,

#                 grant__company=self.company,

#                 grant__is_active=True,

#                 transaction__company=self.company,

#                 transaction__bank_account_id=(
#                     self.bank_account
#                 ),

#                 transaction__txn_type='debit',

#                 transaction__txn_date__range=[
#                     self.start_date,
#                     self.end_date,
#                 ],

#                 allocation_type='destination',
#             )
#             .select_related(
#                 'transaction',
#                 'transaction__particular',
#             )
#             .order_by(
#                 'transaction__txn_date',
#                 'transaction__id',
#             )
#         )

#     # =========================================================
#     # 6. Get ALL Historical Outflow
#     #
#     # IMPORTANT:
#     # There is NO month filter here.
#     # =========================================================

#     def get_total_historical_outflow(self):

#         total_outflow = (
#             TransactionGrantAllocation.objects
#             .filter(
#                 grant_id=self.grant_id,

#                 grant__company=self.company,

#                 grant__is_active=True,

#                 transaction__company=self.company,

#                 transaction__bank_account_id=(
#                     self.bank_account
#                 ),

#                 transaction__txn_type='debit',

#                 allocation_type='destination',
#             )
#             .aggregate(
#                 total=Sum('amount')
#             )['total']
#             or Decimal('0.00')
#         )

#         return Decimal(
#             str(total_outflow)
#         )

#     # =========================================================
#     # 7. Build Particular-wise Report
#     # =========================================================

#     def build_report(
#         self,
#         grant,
#         historical_outflow
#     ):

#         allocations = (
#             self.get_monthly_allocations()
#         )

#         particulars = {}

#         # =====================================================
#         # Process monthly allocations
#         # =====================================================

#         for allocation in allocations:

#             transaction = allocation.transaction

#             particular = transaction.particular

#             # -------------------------------------------------
#             # Particular
#             # -------------------------------------------------

#             if particular:

#                 particular_id = particular.id

#                 particular_name = (
#                     particular.name
#                 )

#                 particular_key = (
#                     particular_id
#                 )

#             else:

#                 particular_id = None

#                 particular_name = (
#                     'Uncategorized'
#                 )

#                 particular_key = (
#                     'uncategorized'
#                 )

#             # -------------------------------------------------
#             # Create Particular
#             # -------------------------------------------------

#             if particular_key not in particulars:

#                 particulars[
#                     particular_key
#                 ] = {

#                     'particular_id': (
#                         particular_id
#                     ),

#                     'particular_name': (
#                         particular_name
#                     ),

#                     'weekly_amounts': {
#                         f'week_{week["week"]}':
#                             Decimal('0.00')
#                         for week in self.weeks
#                     },

#                     'total': Decimal('0.00'),
#                 }

#             # -------------------------------------------------
#             # Find Week
#             # -------------------------------------------------

#             for week in self.weeks:

#                 if (
#                     week['start']
#                     <= transaction.txn_date
#                     <= week['end']
#                 ):

#                     week_key = (
#                         f"week_{week['week']}"
#                     )

#                     particulars[
#                         particular_key
#                     ]['weekly_amounts'][
#                         week_key
#                     ] += allocation.amount

#                     particulars[
#                         particular_key
#                     ]['total'] += (
#                         allocation.amount
#                     )

#                     break

#         # =====================================================
#         # Convert Particulars
#         # =====================================================

#         particular_rows = []

#         for particular_data in (
#             particulars.values()
#         ):

#             row = {

#                 'particular_id': (
#                     particular_data[
#                         'particular_id'
#                     ]
#                 ),

#                 'particular_name': (
#                     particular_data[
#                         'particular_name'
#                     ]
#                 ),

#                 'total': float(
#                     particular_data[
#                         'total'
#                     ]
#                 ),
#             }

#             for week in self.weeks:

#                 key = (
#                     f"week_{week['week']}"
#                 )

#                 row[key] = float(
#                     particular_data[
#                         'weekly_amounts'
#                     ][key]
#                 )

#             particular_rows.append(
#                 row
#             )

#         # =====================================================
#         # Monthly Outflow
#         # =====================================================

#         monthly_outflow = sum(
#             (
#                 Decimal(
#                     str(row['total'])
#                 )
#                 for row in particular_rows
#             ),
#             Decimal('0.00')
#         )

#         # =====================================================
#         # Full Grant Amount
#         # =====================================================

#         grant_amount = (
#             grant.amount
#             or Decimal('0.00')
#         )

#         # =====================================================
#         # Remaining Amount
#         #
#         # NOT month based.
#         # =====================================================

#         remaining_amount = (
#             grant_amount
#             - historical_outflow
#         )

#         if remaining_amount < Decimal('0.00'):

#             remaining_amount = Decimal(
#                 '0.00'
#             )

#         # =====================================================
#         # Grant Response
#         # =====================================================

#         return {

#             # 'grant_id': grant.id,

#             # 'grant_name': grant.name,

#             # 'agency_id': (
#             #     grant.agency.id
#             #     if grant.agency
#             #     else None
#             # ),

#             # 'agency_name': (
#             #     grant.agency.name
#             #     if grant.agency
#             #     else None
#             # ),

#             # Full Grant amount
#             'total_amount': str(
#                 grant_amount
#             ),

#             # # Selected month's outflow
#             'total_outflow': str(
#                 monthly_outflow
#             ),

#             # All historical remaining
#             'remaining_amount': str(
#                 remaining_amount
#             ),

#             'particulars': (
#                 particular_rows
#             ),
#         }

#     # =========================================================
#     # 8. Calculate Weekly Totals
#     # =========================================================

#     def calculate_week_totals(
#         self,
#         report
#     ):

#         week_totals = {}

#         for week in self.weeks:

#             key = (
#                 f"week_{week['week']}"
#             )

#             total = Decimal('0.00')

#             for particular in (
#                 report['particulars']
#             ):

#                 total += Decimal(
#                     str(
#                         particular[key]
#                     )
#                 )

#             week_totals[key] = float(
#                 total
#             )

#         # -----------------------------------------------------
#         # Selected month's total
#         # -----------------------------------------------------

#         week_totals['total'] = float(
#             Decimal(
#                 report['total_outflow']
#             )
#         )

#         return week_totals

#     # =========================================================
#     # 9. Execute
#     # =========================================================

#     def execute(self):

#         self.validate()

#         # -----------------------------------------------------
#         # Get Grant
#         # -----------------------------------------------------

#         grant = self.get_grant()

#         # -----------------------------------------------------
#         # Validate Bank -> Grant assignment
#         # -----------------------------------------------------

#         self.validate_bank_grant_relation()

#         # -----------------------------------------------------
#         # Calculate historical outflow ONCE
#         # -----------------------------------------------------

#         historical_outflow = (
#             self.get_total_historical_outflow()
#         )

#         # -----------------------------------------------------
#         # Build monthly report
#         # -----------------------------------------------------

#         report = self.build_report(
#             grant=grant,
#             historical_outflow=(
#                 historical_outflow
#             )
#         )

#         # -----------------------------------------------------
#         # Weekly totals
#         # -----------------------------------------------------

#         week_totals = (
#             self.calculate_week_totals(
#                 report
#             )
#         )

#         # =====================================================
#         # Global Summary
#         #
#         # IMPORTANT:
#         # These values are NOT based on month.
#         # =====================================================

#         summary = {

#             'total_grant_amount': (
#                 report['total_amount']
#             ),

#             'total_outflow': str(
#                 historical_outflow
#             ),

#             'total_remaining': (
#                 report['remaining_amount']
#             ),
#         }

#         # =====================================================
#         # Final Response
#         # =====================================================

#         return {

#             'success': True,

#             'month': self.month,

#             'year': self.year,

#             'bank_account_id': (
#                 self.bank_account
#             ),

#             'grant_id': (
#                 self.grant_id
#             ),

#             'weeks': [

#                 {
#                     'week': week['week'],

#                     'label': week['label'],
#                 }

#                 for week in self.weeks
#             ],

#             # -------------------------------------------------
#             # GLOBAL Grant Summary
#             # -------------------------------------------------

#             'summary': summary,

#             # -------------------------------------------------
#             # MONTHLY Grant-wise Outflow
#             # -------------------------------------------------

#             'grant_wise_outflow': {

#                 'rows': [
#                     report
#                 ],

#                 'totals': week_totals,

#             },
#         }





import calendar

from datetime import date
from decimal import Decimal

from django.db.models import Sum

from banklist.models import (
    Grant,
    TransactionGrantAllocation,
)


class GrantWiseOutflowService:

    """
    Generate Grant-wise outflow report for:

        Bank -> Grant -> Particular -> Week

    Business Rules
    --------------

    1. Bank and Grant are both required.

    2. Grant must belong to the user's company.

    3. Grant must actually be assigned to the selected Bank.

    4. The grant amount shown depends on the selected Bank.

       Example:

           Original Grant = 150000

           A1 receives = 150000
           A1 -> A2 = 45000

           A1 Grant Amount = 150000
           A2 Grant Amount = 45000

    5. Monthly outflow:

       - Transaction type = debit
       - Allocation type = destination
       - Selected Bank
       - Selected Grant
       - Selected Month

    6. Historical outflow:

       - All debit allocations
       - Selected Bank
       - Selected Grant
       - No month restriction

    7. Remaining amount:

       Amount received by selected Bank
       -
       Historical outflow from selected Bank
    """

    def __init__(
        self,
        company,
        month,
        year,
        bank_account,
        grant_id
    ):

        self.company = company
        self.month = month
        self.year = year
        self.bank_account = bank_account
        self.grant_id = grant_id

        self.start_date = None
        self.end_date = None
        self.weeks = None

    # =========================================================
    # 1. Validate Request
    # =========================================================

    def validate(self):

        if self.month is None:
            raise ValueError(
                "Month is required."
            )

        if self.year is None:
            raise ValueError(
                "Year is required."
            )

        if self.bank_account is None:
            raise ValueError(
                "bank_account_id is required."
            )

        if self.grant_id is None:
            raise ValueError(
                "grant_id is required."
            )

        try:

            self.month = int(
                self.month
            )

        except (
            TypeError,
            ValueError
        ):

            raise ValueError(
                "Invalid month."
            )

        try:

            self.year = int(
                self.year
            )

        except (
            TypeError,
            ValueError
        ):

            raise ValueError(
                "Invalid year."
            )

        try:

            self.bank_account = int(
                self.bank_account
            )

        except (
            TypeError,
            ValueError
        ):

            raise ValueError(
                "Invalid bank_account_id."
            )

        try:

            self.grant_id = int(
                self.grant_id
            )

        except (
            TypeError,
            ValueError
        ):

            raise ValueError(
                "Invalid grant_id."
            )

        if (
            self.month < 1
            or self.month > 12
        ):

            raise ValueError(
                "Month must be between 1 and 12."
            )

        if self.year < 1:

            raise ValueError(
                "Invalid year."
            )

        last_day = calendar.monthrange(
            self.year,
            self.month
        )[1]

        self.start_date = date(
            self.year,
            self.month,
            1
        )

        self.end_date = date(
            self.year,
            self.month,
            last_day
        )

        self.weeks = (
            self.get_week_ranges()
        )

    # =========================================================
    # 2. Week Ranges
    # =========================================================

    def get_week_ranges(self):

        last_day = calendar.monthrange(
            self.year,
            self.month
        )[1]

        week_ranges = []

        start_day = 1
        week_number = 1

        while start_day <= last_day:

            end_day = min(
                start_day + 6,
                last_day
            )

            start = date(
                self.year,
                self.month,
                start_day
            )

            end = date(
                self.year,
                self.month,
                end_day
            )

            week_ranges.append(
                {
                    "week": week_number,

                    "start": start,

                    "end": end,

                    "label": (
                        f"{start.strftime('%d %b')} - "
                        f"{end.strftime('%d %b')}"
                    ),
                }
            )

            week_number += 1

            start_day = end_day + 1

        return week_ranges

    # =========================================================
    # 3. Get Grant
    # =========================================================

    def get_grant(self):

        try:

            grant = (
                Grant.objects
                .select_related(
                    "agency"
                )
                .get(
                    id=self.grant_id,
                    company=self.company,
                    is_active=True
                )
            )

        except Grant.DoesNotExist:

            raise ValueError(
                "Grant not found or inactive."
            )

        return grant

    # =========================================================
    # 4. Validate Grant -> Bank Assignment
    #
    # Grant must have actually entered this Bank.
    # =========================================================

    def validate_bank_grant_relation(self):

        exists = (
            TransactionGrantAllocation.objects
            .filter(
                grant_id=self.grant_id,

                grant__company=self.company,

                grant__is_active=True,

                transaction__company=self.company,

                transaction__bank_account_id=(
                    self.bank_account
                ),

                transaction__txn_type="credit",

                allocation_type="source",
            )
            .exists()
        )

        if not exists:

            raise ValueError(
                "Selected Grant is not assigned "
                "to the selected Bank."
            )

    # =========================================================
    # 5. Get Grant Amount Available in Selected Bank
    #
    # IMPORTANT:
    #
    # We do NOT use Grant.amount directly.
    #
    # We calculate how much of this Grant was actually
    # credited into the selected Bank.
    #
    # This supports:
    #
    # A1 = Original Grant ₹150000
    # A2 = Internal Transfer ₹45000
    #
    # Result:
    #
    # A1 -> ₹150000
    # A2 -> ₹45000
    # =========================================================

    def get_bank_grant_amount(self):

        total_received = (
            TransactionGrantAllocation.objects
            .filter(
                grant_id=self.grant_id,

                grant__company=self.company,

                grant__is_active=True,

                transaction__company=self.company,

                transaction__bank_account_id=(
                    self.bank_account
                ),

                transaction__txn_type="credit",

                allocation_type="source",
            )
            .aggregate(
                total=Sum("amount")
            )
            .get("total")
            or Decimal("0.00")
        )

        return Decimal(
            str(total_received)
        )

    # =========================================================
    # 6. Get Monthly Debit Allocations
    # =========================================================

    def get_monthly_allocations(self):

        return (
            TransactionGrantAllocation.objects
            .filter(
                grant_id=self.grant_id,

                grant__company=self.company,

                grant__is_active=True,

                transaction__company=self.company,

                transaction__bank_account_id=(
                    self.bank_account
                ),

                transaction__txn_type="debit",

                transaction__txn_date__range=[
                    self.start_date,
                    self.end_date,
                ],

                allocation_type="destination",
            )
            .select_related(
                "transaction",
                "transaction__particular",
            )
            .order_by(
                "transaction__txn_date",
                "transaction__id",
            )
        )

    # =========================================================
    # 7. Get Historical Outflow
    #
    # No month restriction.
    # Only selected Bank + selected Grant.
    # =========================================================

    def get_total_historical_outflow(self):

        total_outflow = (
            TransactionGrantAllocation.objects
            .filter(
                grant_id=self.grant_id,

                grant__company=self.company,

                grant__is_active=True,

                transaction__company=self.company,

                transaction__bank_account_id=(
                    self.bank_account
                ),

                transaction__txn_type="debit",

                allocation_type="destination",
            )
            .aggregate(
                total=Sum("amount")
            )
            .get("total")
            or Decimal("0.00")
        )

        return Decimal(
            str(total_outflow)
        )

    # =========================================================
    # 8. Build Particular-wise Report
    # =========================================================

    def build_report(
        self,
        grant_amount,
        historical_outflow
    ):

        allocations = (
            self.get_monthly_allocations()
        )

        particular_map = {}

        # -----------------------------------------------------
        # Initialize week amounts
        # -----------------------------------------------------

        for allocation in allocations:

            transaction = (
                allocation.transaction
            )

            particular = (
                transaction.particular
            )

            if particular:

                particular_id = (
                    particular.id
                )

                particular_name = (
                    particular.name
                )

            else:

                particular_id = None

                particular_name = (
                    "Uncategorized"
                )

            key = (
                particular_id,
                particular_name
            )

            if key not in particular_map:

                particular_map[key] = {

                    "particular_id": (
                        particular_id
                    ),

                    "particular_name": (
                        particular_name
                    ),

                    "weekly_amounts": {

                        f"week_{week['week']}": (
                            Decimal("0.00")
                        )

                        for week in self.weeks
                    },

                    "total": (
                        Decimal("0.00")
                    ),
                }

            # -------------------------------------------------
            # Find Week
            # -------------------------------------------------

            for week in self.weeks:

                if (

                    week["start"]
                    <= transaction.txn_date
                    <= week["end"]

                ):

                    week_key = (
                        f"week_{week['week']}"
                    )

                    particular_map[key][
                        "weekly_amounts"
                    ][week_key] += (
                        allocation.amount
                    )

                    particular_map[key][
                        "total"
                    ] += (
                        allocation.amount
                    )

                    break

        # =====================================================
        # Convert to Response Rows
        # =====================================================

        particular_rows = []

        for particular_data in (
            particular_map.values()
        ):

            row = {

                "particular_id": (
                    particular_data[
                        "particular_id"
                    ]
                ),

                "particular_name": (
                    particular_data[
                        "particular_name"
                    ]
                ),

                "total": float(
                    particular_data[
                        "total"
                    ]
                ),
            }

            for week in self.weeks:

                key = (
                    f"week_{week['week']}"
                )

                row[key] = float(

                    particular_data[
                        "weekly_amounts"
                    ][key]

                )

            particular_rows.append(
                row
            )

        # =====================================================
        # Monthly Outflow
        # =====================================================

        monthly_outflow = sum(
            (
                Decimal(
                    str(row["total"])
                )
                for row in particular_rows
            ),
            Decimal("0.00")
        )

        # =====================================================
        # Remaining Amount
        #
        # Selected Bank Grant Amount
        # -
        # Historical Outflow
        # =====================================================

        remaining_amount = (

            grant_amount
            - historical_outflow

        )

        if remaining_amount < Decimal("0.00"):

            remaining_amount = (
                Decimal("0.00")
            )

        # =====================================================
        # Report Response
        # =====================================================

        return {

            # Amount of Grant actually received
            # by the selected Bank

            "total_amount": str(
                grant_amount
            ),

            # Selected month's outflow

            "total_outflow": str(
                monthly_outflow
            ),

            # Historical remaining amount

            "remaining_amount": str(
                remaining_amount
            ),

            "particulars": (
                particular_rows
            ),
        }

    # =========================================================
    # 9. Calculate Weekly Totals
    # =========================================================

    def calculate_week_totals(
        self,
        report
    ):

        week_totals = {}

        for week in self.weeks:

            key = (
                f"week_{week['week']}"
            )

            total = Decimal("0.00")

            for particular in (
                report["particulars"]
            ):

                total += Decimal(
                    str(
                        particular[key]
                    )
                )

            week_totals[key] = float(
                total
            )

        # -----------------------------------------------------
        # Selected month's total
        # -----------------------------------------------------

        week_totals["total"] = float(
            Decimal(
                report["total_outflow"]
            )
        )

        return week_totals

    # =========================================================
    # 10. Execute
    # =========================================================

    def execute(self):

        self.validate()

        # -----------------------------------------------------
        # Get Grant
        # -----------------------------------------------------

        grant = (
            self.get_grant()
        )

        # -----------------------------------------------------
        # Validate Grant -> Bank relation
        # -----------------------------------------------------

        self.validate_bank_grant_relation()

        # -----------------------------------------------------
        # Get amount of this Grant actually received
        # by the selected Bank
        # -----------------------------------------------------

        bank_grant_amount = (
            self.get_bank_grant_amount()
        )

        # -----------------------------------------------------
        # Historical Outflow
        # -----------------------------------------------------

        historical_outflow = (
            self.get_total_historical_outflow()
        )

        # -----------------------------------------------------
        # Build Monthly Report
        # -----------------------------------------------------

        report = self.build_report(
            grant_amount=bank_grant_amount,
            historical_outflow=(
                historical_outflow
            )
        )

        # -----------------------------------------------------
        # Weekly Totals
        # -----------------------------------------------------

        week_totals = (
            self.calculate_week_totals(
                report
            )
        )

        # =====================================================
        # Summary
        #
        # Bank-specific.
        # Not based on selected month.
        # =====================================================

        summary = {

            "total_grant_amount": (
                report["total_amount"]
            ),

            "total_outflow": str(
                historical_outflow
            ),

            "total_remaining": (
                report["remaining_amount"]
            ),
        }

        # =====================================================
        # Final Response
        # =====================================================

        return {

            "success": True,

            "month": self.month,

            "year": self.year,

            "bank_account_id": (
                self.bank_account
            ),

            "grant_id": (
                self.grant_id
            ),

            "weeks": [

                {

                    "week": week["week"],

                    "label": week["label"],
                }

                for week in self.weeks

            ],

            "summary": summary,

            "grant_wise_outflow": {

                "rows": [
                    report
                ],

                "totals": (
                    week_totals
                ),
            },
        }