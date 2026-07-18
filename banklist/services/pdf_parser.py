"""
services/pdf_parser.py
======================
Bank Statement PDF Parser — tested against real DBS, SBI, HDFC statements.

Strategy per bank
-----------------
DBS   → word-position parser  (columns identified by x0 coordinate)
HDFC  → word-position parser  (columns identified by x0 coordinate)
SBI   → pdfplumber table extraction (pdfplumber detects the table perfectly)
ICICI → table extraction fallback
AXIS  → table extraction fallback
Generic → table → text fallback chain

All parsers return the same normalised ParsedTransaction dataclass so the
rest of your system (views.py, reconciliation engine) never needs to change
when a new bank is added.
"""

import io
import re
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import List, Optional

import pdfplumber

from .ollama_extractor import OllamaExtractionError, extract_statement_transactions

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ParsedTransaction:
    txn_date:   date
    value_date: Optional[date]
    description: str
    ref_no:     str
    utr_no:     str
    txn_type:   str          # 'debit' | 'credit'
    amount:     Decimal
    balance:    Optional[Decimal]
    cheque_no:  str = ''


@dataclass
class ParseResult:
    bank_name:        str
    account_no:       str
    account_name:     str
    transactions:     List[ParsedTransaction] = field(default_factory=list)
    errors:           List[str]               = field(default_factory=list)
    statement_period: dict                    = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_amount(val) -> Optional[Decimal]:
    """'1,23,456.78' / '-29,51,582.88' / '₹1000.00' → Decimal or None."""
    if not val:
        return None
    cleaned = re.sub(r'[₹$,\s]', '', str(val).strip())
    # keep a leading minus (negative balances)
    try:
        d = Decimal(cleaned)
        return d
    except (InvalidOperation, ValueError):
        return None


def _parse_amount_positive(val) -> Optional[Decimal]:
    """Same as above but only returns value if > 0 (used for debit/credit)."""
    d = _parse_amount(val)
    return d if d and d > 0 else None


def _parse_date(s, fmts: List[str]) -> Optional[date]:
    s = str(s).strip() if s else ''
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _extract_utr(text: str) -> str:
    """Pull UTR / NEFT reference from description text."""
    patterns = [
        r'\b(SBIN\d{9,18})\b',
        r'\b(HDFC[A-Z0-9]{6,18})\b',
        r'\b(DBSS[A-Z0-9]{6,15})\b',
        r'\b(UTIB[A-Z0-9]{6,15})\b',
        r'\b(CNAE[A-Z0-9]{4,12})\b',
        r'UTR\s*(?:NO)?[:\s]*([A-Z0-9]{8,25})',
        r'NEFT\s+(?:UTR\s+)?NO[:\s]*([A-Z0-9]{8,25})',
        r'\b([A-Z]{4}[A-Z0-9]{6,20})\b',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).upper()
    return ''


def _clean_description(text: str) -> str:
    return ' '.join(text.split())[:500]


def _deduplicate(txns: List[ParsedTransaction]) -> List[ParsedTransaction]:
    seen, out = set(), []
    for t in txns:
        key = (
            t.txn_date.isoformat(),
            str(t.amount),
            t.txn_type,
            t.utr_no[:20],
            t.description[:30],
        )
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out


def _parse_iso_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def _extract_pdf_text_with_ocr(file_bytes: bytes) -> str:
    """Fallback text extraction for scanned statement PDFs."""
    try:
        import fitz
        import pytesseract
        from PIL import Image

        doc = fitz.open(stream=file_bytes, filetype="pdf")
        pages = []
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            pages.append(pytesseract.image_to_string(img, lang="eng"))
        return "\n".join(pages).strip()
    except Exception as exc:
        logger.warning("Statement OCR fallback failed: %s", exc)
        return ""


def _is_excel_file(file_name: str) -> bool:
    return str(file_name or '').lower().endswith(('.xlsx', '.xlsm'))


def _is_image_file(file_name: str) -> bool:
    return str(file_name or '').lower().endswith(('.png', '.jpg', '.jpeg'))


def _extract_excel_text(file_bytes: bytes) -> str:
    """Extract workbook cell text for AI-assisted statement parsing."""
    try:
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
        chunks = []
        for sheet in wb.worksheets:
            chunks.append(f"Sheet: {sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                values = [str(cell).strip() for cell in row if cell not in (None, '')]
                if values:
                    chunks.append(" | ".join(values))
        return "\n".join(chunks).strip()
    except Exception as exc:
        logger.warning("Excel statement extraction failed: %s", exc)
        return ""


def _extract_image_text(file_bytes: bytes) -> str:
    """OCR an image bank statement so Ollama can extract transaction rows."""
    try:
        import pytesseract
        from PIL import Image, ImageEnhance

        img = Image.open(io.BytesIO(file_bytes))
        if img.mode != "L":
            img = img.convert("L")
        img = ImageEnhance.Contrast(img).enhance(2.0)
        return pytesseract.image_to_string(img, lang="eng").strip()
    except Exception as exc:
        logger.warning("Image statement OCR failed: %s", exc)
        return ""


def _ollama_statement_result(text: str) -> Optional[ParseResult]:
    if not text.strip():
        return None
    try:
        ai = extract_statement_transactions(text)
    except OllamaExtractionError as exc:
        logger.warning("Ollama statement fallback skipped: %s", exc)
        return None
    except Exception as exc:
        logger.warning("Ollama statement fallback failed: %s", exc, exc_info=True)
        return None

    txns = []
    for item in ai.get("transactions") or []:
        txn_date = _parse_iso_date(item.get("txn_date"))
        if not txn_date:
            continue
        amount = item.get("amount")
        if not amount or amount <= 0:
            continue
        txns.append(ParsedTransaction(
            txn_date=txn_date,
            value_date=_parse_iso_date(item.get("value_date")),
            description=_clean_description(item.get("description") or ""),
            ref_no=item.get("ref_no") or "",
            utr_no=(item.get("utr_no") or _extract_utr(item.get("description") or "")),
            txn_type=item.get("txn_type"),
            amount=amount,
            balance=item.get("balance"),
        ))

    if not txns:
        return None

    return ParseResult(
        bank_name=ai.get("bank_name") or "UNKNOWN",
        account_no=ai.get("account_no") or "",
        account_name=ai.get("account_name") or "",
        transactions=_deduplicate(txns),
        errors=[],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Bank detection + metadata
# ─────────────────────────────────────────────────────────────────────────────

_BANK_SIGNATURES = {
    # !! ORDER MATTERS !!
    # DBS   — unique: "EBUSINESS LITE" product type, 8160210 account prefix
    # HDFC  — unique: "WithdrawalAmt" / "DepositAmt" (words run together in their PDF)
    #          Must come BEFORE SBI because SBI narrations mention HDFC destinations
    # SBI   — unique: "IFS Code" header field contains SBIN
    # ICICI / AXIS — generic fallback
    'DBS':   [r'EBUSINESS LITE', r'DBS BANK', r'8160210', r'DBSS\d{4}'],
    'HDFC':  [r'WithdrawalAmt', r'DepositAmt', r'ASCENTCURRENT', r'HDFC0004\d+'],
    'SBI':   [r'STATE BANK OF INDIA', r'IFS\s*Code\s*[:\s]+SBIN', r'SBIN0010\d+'],
    'ICICI': [r'ICICI BANK', r'ICIC\d{4}'],
    'AXIS':  [r'AXIS BANK', r'UTIB\d{4}'],
}


def _detect_bank(text: str) -> str:
    upper = text.upper()
    for bank, patterns in _BANK_SIGNATURES.items():
        if any(re.search(p, upper) for p in patterns):
            return bank
    return 'UNKNOWN'


def _extract_metadata(text: str) -> tuple:
    """Return (account_no, account_name)."""
    acc_no = ''
    acc_name = ''

    for pat in [
        r'Account\s*Number\s*[:\-]?\s*([\d\-]{8,25})',
        r'A/C\s*No\.?\s*[:\-]?\s*([\d\-]{8,25})',
        r'Account\s*No\.?\s*[:\-]?\s*([\d\-]{8,25})',
        r'(\d{10,20})',
    ]:
        m = re.search(pat, text, re.I)
        if m:
            acc_no = m.group(1).strip()
            break

    for pat in [
        r'Account\s*Name\s*[:\-]?\s*([^\n\r:]+)',
        r'Customer\s*Name\s*[:\-]?\s*([^\n\r:]+)',
        r'M/S\.?\s+([^\n\r]+)',
    ]:
        m = re.search(pat, text, re.I)
        if m:
            acc_name = m.group(1).strip()
            break

    return acc_no, acc_name


# ─────────────────────────────────────────────────────────────────────────────
# DBS parser  (word-position based)
# Columns (x0 boundaries in pts):
#   Trans.Date 0–95 | Value Date 95–150 | Details 150–310
#   Debits 310–430  | Credits 430–520   | Running Balance 520–620
# ─────────────────────────────────────────────────────────────────────────────

_DBS_COLS = {
    'trans_date':  (0,   95),
    'value_date':  (95,  150),
    'details':     (150, 310),
    'debits':      (310, 430),
    'credits':     (430, 520),
    'balance':     (520, 620),
}
_DBS_DATE_FMTS = ['%d-%b-%Y', '%d/%m/%Y', '%d-%m-%Y']


def _in_dbs(word: dict, col: str) -> bool:
    x0, x1 = _DBS_COLS[col]
    return x0 <= word['x0'] < x1


def _parse_dbs(pdf) -> tuple:
    txns, errors = [], []

    for page_num, page in enumerate(pdf.pages, 1):
        try:
            words = page.extract_words(x_tolerance=3, y_tolerance=3)
            rows: dict = defaultdict(list)
            for w in words:
                rows[round(w['top'])].append(w)

            pending = None

            for top in sorted(rows):
                rw = sorted(rows[top], key=lambda w: w['x0'])
                if not rw:
                    continue

                first = rw[0]
                txn_date = (_in_dbs(first, 'trans_date') and
                            _parse_date(first['text'], _DBS_DATE_FMTS))

                if txn_date:
                    # Save previous
                    if pending:
                        t = _build_dbs_txn(pending)
                        if t:
                            txns.append(t)
                    # New transaction
                    pending = {
                        'date': txn_date,
                        'desc': [],
                        'debit': None,
                        'credit': None,
                        'balance': None,
                    }
                    for w in rw[1:]:
                        txt = w['text']
                        if _in_dbs(w, 'details'):
                            pending['desc'].append(txt)
                        elif _in_dbs(w, 'debits'):
                            a = _parse_amount_positive(txt)
                            if a:
                                pending['debit'] = a
                        elif _in_dbs(w, 'credits'):
                            a = _parse_amount_positive(txt)
                            if a:
                                pending['credit'] = a
                        elif _in_dbs(w, 'balance'):
                            # balance can be negative
                            a = _parse_amount(txt.replace('-', ''))
                            if a:
                                pending['balance'] = a
                else:
                    # Continuation row
                    if pending:
                        for w in rw:
                            txt = w['text']
                            if _in_dbs(w, 'details'):
                                pending['desc'].append(txt)
                            elif _in_dbs(w, 'debits') and pending['debit'] is None:
                                a = _parse_amount_positive(txt)
                                if a:
                                    pending['debit'] = a
                            elif _in_dbs(w, 'credits') and pending['credit'] is None:
                                a = _parse_amount_positive(txt)
                                if a:
                                    pending['credit'] = a
                            elif _in_dbs(w, 'balance') and pending['balance'] is None:
                                a = _parse_amount(txt.replace('-', ''))
                                if a:
                                    pending['balance'] = a

            if pending:
                t = _build_dbs_txn(pending)
                if t:
                    txns.append(t)

        except Exception as e:
            errors.append(f'DBS page {page_num}: {e}')
            logger.warning('DBS page %d error: %s', page_num, e)

    return txns, errors


def _build_dbs_txn(p: dict) -> Optional[ParsedTransaction]:
    if not p.get('date'):
        return None
    debit  = p.get('debit')
    credit = p.get('credit')

    if debit and debit > 0:
        txn_type, amount = 'debit', debit
    elif credit and credit > 0:
        txn_type, amount = 'credit', credit
    else:
        return None

    desc = _clean_description(' '.join(p['desc']))
    utr  = _extract_utr(desc)

    return ParsedTransaction(
        txn_date=p['date'],
        value_date=None,
        description=desc,
        ref_no=utr,
        utr_no=utr,
        txn_type=txn_type,
        amount=amount,
        balance=p.get('balance'),
    )


# ─────────────────────────────────────────────────────────────────────────────
# SBI parser  (pdfplumber table extraction — works perfectly on SBI PDFs)
# Columns: Txn Date | Value Date | Description | Ref No./Cheque No. |
#          Branch Code | Debit | Credit | Balance
# ─────────────────────────────────────────────────────────────────────────────

_SBI_DATE_FMTS = ['%d/%m/%Y', '%d-%m-%Y', '%d/%m/%y']

# keywords → standard field name
_SBI_HEADER_MAP = {
    'txn date': 'date',
    'date': 'date',
    'value date': 'vdate',
    'description': 'desc',
    'ref no': 'ref',
    'cheque': 'ref',
    'debit': 'debit',
    'credit': 'credit',
    'balance': 'balance',
}


def _map_sbi_headers(headers: list) -> dict:
    """Return {field: col_index} from header list."""
    col = {}
    for i, h in enumerate(headers):
        h_clean = h.lower().replace('\n', ' ').strip()
        for keyword, field in _SBI_HEADER_MAP.items():
            if keyword in h_clean:
                if field not in col:          # first match wins
                    col[field] = i
                break
    return col


def _parse_sbi(pdf) -> tuple:
    txns, errors = [], []

    for page_num, page in enumerate(pdf.pages, 1):
        try:
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue

                # Find header row
                hdr_idx = None
                for i, row in enumerate(table):
                    joined = ' '.join(str(c) for c in row if c).upper()
                    if ('DEBIT' in joined and 'CREDIT' in joined) or 'TXN DATE' in joined:
                        hdr_idx = i
                        break
                if hdr_idx is None:
                    continue

                headers = [str(c or '').strip() for c in table[hdr_idx]]
                col = _map_sbi_headers(headers)

                if 'date' not in col:
                    continue

                for row in table[hdr_idx + 1:]:
                    if not row:
                        continue
                    try:
                        date_raw = str(row[col['date']] or '').split('\n')[0].strip()
                        txn_date = _parse_date(date_raw, _SBI_DATE_FMTS)
                        if not txn_date:
                            continue

                        vdate = None
                        if 'vdate' in col:
                            vdate = _parse_date(
                                str(row[col['vdate']] or '').split('\n')[0].strip(),
                                _SBI_DATE_FMTS
                            )

                        desc = _clean_description(
                            str(row[col.get('desc', 2)] or '').replace('\n', ' ')
                        )
                        ref_raw = str(row[col.get('ref', 3)] or '').replace('\n', ' ').strip()
                        # First token of ref column is usually the UTR/ref
                        ref_no = ref_raw.split()[0] if ref_raw else ''

                        debit  = _parse_amount_positive(row[col['debit']])  if 'debit'  in col else None
                        credit = _parse_amount_positive(row[col['credit']]) if 'credit' in col else None

                        # Balance may be negative (credit card / OD account)
                        bal = None
                        if 'balance' in col:
                            bal = _parse_amount(str(row[col['balance']] or '').replace(',', '').replace(' ', ''))

                        if debit and debit > 0:
                            txn_type, amount = 'debit', debit
                        elif credit and credit > 0:
                            txn_type, amount = 'credit', credit
                        else:
                            continue

                        utr = _extract_utr(desc + ' ' + ref_no)

                        txns.append(ParsedTransaction(
                            txn_date=txn_date,
                            value_date=vdate,
                            description=desc,
                            ref_no=ref_no,
                            utr_no=utr,
                            txn_type=txn_type,
                            amount=amount,
                            balance=bal,
                        ))
                    except Exception as row_err:
                        logger.debug('SBI row error: %s', row_err)

        except Exception as e:
            errors.append(f'SBI page {page_num}: {e}')
            logger.warning('SBI page %d error: %s', page_num, e)

    return txns, errors


# ─────────────────────────────────────────────────────────────────────────────
# HDFC parser  (word-position based)
# Columns (x0 in pts, 638pt wide page):
#   Date 28–68 | Narration 68–290 | Chq/Ref 290–367 | Value Dt 362–410
#   Withdrawal 405–492 | Deposit 490–565 | Closing Balance 562–640
# ─────────────────────────────────────────────────────────────────────────────

_HDFC_COLS = {
    'date':       (28,  68),
    'narration':  (68,  290),
    'ref_no':     (290, 367),
    'value_date': (362, 410),
    'withdrawal': (405, 492),
    'deposit':    (490, 565),
    'balance':    (562, 640),
}
_HDFC_DATE_FMTS = ['%d/%m/%y', '%d/%m/%Y']


def _in_hdfc(word: dict, col: str) -> bool:
    x0, x1 = _HDFC_COLS[col]
    return x0 <= word['x0'] < x1


def _parse_hdfc(pdf) -> tuple:
    txns, errors = [], []

    for page_num, page in enumerate(pdf.pages, 1):
        try:
            words = page.extract_words(x_tolerance=2, y_tolerance=3)
            rows: dict = defaultdict(list)
            for w in words:
                rows[round(w['top'])].append(w)

            pending = None

            for top in sorted(rows):
                rw = sorted(rows[top], key=lambda w: w['x0'])
                if not rw:
                    continue

                first = rw[0]
                is_txn = (
                    _in_hdfc(first, 'date') and
                    bool(re.match(r'^\d{2}/\d{2}/\d{2,4}$', first['text']))
                )

                if is_txn:
                    if pending:
                        t = _build_hdfc_txn(pending)
                        if t:
                            txns.append(t)
                    pending = {
                        'date_str':   first['text'],
                        'narration':  [],
                        'ref':        '',
                        'value_date': None,
                        'withdrawal': None,
                        'deposit':    None,
                        'balance':    None,
                    }
                    for w in rw[1:]:
                        txt = w['text']
                        if _in_hdfc(w, 'narration'):
                            pending['narration'].append(txt)
                        elif _in_hdfc(w, 'ref_no'):
                            pending['ref'] = txt
                        elif _in_hdfc(w, 'value_date'):
                            pending['value_date'] = _parse_date(txt, _HDFC_DATE_FMTS)
                        elif _in_hdfc(w, 'withdrawal'):
                            a = _parse_amount_positive(txt)
                            if a:
                                pending['withdrawal'] = a
                        elif _in_hdfc(w, 'deposit'):
                            a = _parse_amount_positive(txt)
                            if a:
                                pending['deposit'] = a
                        elif _in_hdfc(w, 'balance'):
                            a = _parse_amount_positive(txt)
                            if a:
                                pending['balance'] = a
                else:
                    if pending:
                        for w in rw:
                            txt = w['text']
                            if _in_hdfc(w, 'narration'):
                                pending['narration'].append(txt)
                            elif _in_hdfc(w, 'withdrawal') and pending['withdrawal'] is None:
                                a = _parse_amount_positive(txt)
                                if a:
                                    pending['withdrawal'] = a
                            elif _in_hdfc(w, 'deposit') and pending['deposit'] is None:
                                a = _parse_amount_positive(txt)
                                if a:
                                    pending['deposit'] = a
                            elif _in_hdfc(w, 'balance') and pending['balance'] is None:
                                a = _parse_amount_positive(txt)
                                if a:
                                    pending['balance'] = a

            if pending:
                t = _build_hdfc_txn(pending)
                if t:
                    txns.append(t)

        except Exception as e:
            errors.append(f'HDFC page {page_num}: {e}')
            logger.warning('HDFC page %d error: %s', page_num, e)

    return txns, errors


def _build_hdfc_txn(p: dict) -> Optional[ParsedTransaction]:
    txn_date = _parse_date(p['date_str'], _HDFC_DATE_FMTS)
    if not txn_date:
        return None

    wd  = p.get('withdrawal')
    dep = p.get('deposit')

    if wd and wd > 0:
        txn_type, amount = 'debit', wd
    elif dep and dep > 0:
        txn_type, amount = 'credit', dep
    else:
        return None

    desc = _clean_description(' '.join(p['narration']))
    ref  = p.get('ref', '')
    utr  = _extract_utr(desc + ' ' + ref)

    return ParsedTransaction(
        txn_date=txn_date,
        value_date=p.get('value_date'),
        description=desc,
        ref_no=ref,
        utr_no=utr,
        txn_type=txn_type,
        amount=amount,
        balance=p.get('balance'),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Generic table parser  (ICICI, AXIS, unknown banks)
# ─────────────────────────────────────────────────────────────────────────────

_GENERIC_DATE_FMTS = [
    '%d/%m/%Y', '%d-%m-%Y', '%d/%m/%y', '%d-%m-%y',
    '%d-%b-%Y', '%d-%b-%y', '%d %b %Y',
]

_GENERIC_HDR = {
    'date': 'date', 'txn date': 'date', 'transaction date': 'date',
    'value date': 'vdate',
    'description': 'desc', 'narration': 'desc', 'particulars': 'desc',
    'ref no': 'ref', 'cheque': 'ref', 'reference': 'ref',
    'debit': 'debit', 'withdrawal': 'debit', 'dr': 'debit',
    'credit': 'credit', 'deposit': 'credit', 'cr': 'credit',
    'balance': 'balance', 'closing balance': 'balance',
}


def _parse_generic(pdf) -> tuple:
    txns, errors = [], []

    for page_num, page in enumerate(pdf.pages, 1):
        try:
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue

                hdr_idx = None
                for i, row in enumerate(table):
                    joined = ' '.join(str(c) for c in row if c).lower()
                    score = sum(1 for k in ['date', 'debit', 'credit', 'balance'] if k in joined)
                    if score >= 2:
                        hdr_idx = i
                        break

                start = (hdr_idx + 1) if hdr_idx is not None else 0
                headers = [str(c or '').strip().lower() for c in table[hdr_idx or 0]]
                col: dict = {}
                for i, h in enumerate(headers):
                    for kw, fld in _GENERIC_HDR.items():
                        if kw in h and fld not in col:
                            col[fld] = i
                            break

                for row in table[start:]:
                    if not row:
                        continue
                    date_raw = str(row[col.get('date', 0)] or '').split('\n')[0].strip()
                    txn_date = _parse_date(date_raw, _GENERIC_DATE_FMTS)
                    if not txn_date:
                        continue

                    desc  = _clean_description(str(row[col.get('desc', 1)] or '').replace('\n', ' '))
                    ref   = str(row[col.get('ref', 2)] or '').replace('\n', ' ').strip()
                    debit  = _parse_amount_positive(row[col['debit']])  if 'debit'  in col else None
                    credit = _parse_amount_positive(row[col['credit']]) if 'credit' in col else None
                    bal    = _parse_amount(row[col['balance']])          if 'balance' in col else None

                    if debit:
                        txn_type, amount = 'debit', debit
                    elif credit:
                        txn_type, amount = 'credit', credit
                    else:
                        continue

                    utr = _extract_utr(desc + ' ' + ref)
                    txns.append(ParsedTransaction(
                        txn_date=txn_date,
                        value_date=None,
                        description=desc,
                        ref_no=ref,
                        utr_no=utr,
                        txn_type=txn_type,
                        amount=amount,
                        balance=bal,
                    ))

        except Exception as e:
            errors.append(f'Generic page {page_num}: {e}')

    return txns, errors


# ─────────────────────────────────────────────────────────────────────────────
# Main parser class
# ─────────────────────────────────────────────────────────────────────────────

class BankStatementParser:

    def parse_pdf(self, file_bytes: bytes, file_name: str = "") -> ParseResult:
        try:
            if _is_excel_file(file_name):
                full_text = _extract_excel_text(file_bytes)
                ai_result = _ollama_statement_result(full_text)
                if ai_result:
                    logger.info(
                        'Parsed %d transactions from Excel statement using Ollama',
                        len(ai_result.transactions),
                    )
                    return ai_result
                return ParseResult(
                    bank_name='UNKNOWN',
                    account_no='',
                    account_name='',
                    errors=['No transactions extracted from Excel statement'],
                )

            if _is_image_file(file_name):
                full_text = _extract_image_text(file_bytes)
                ai_result = _ollama_statement_result(full_text)
                if ai_result:
                    logger.info(
                        'Parsed %d transactions from image statement using Ollama',
                        len(ai_result.transactions),
                    )
                    return ai_result
                return ParseResult(
                    bank_name='UNKNOWN',
                    account_no='',
                    account_name='',
                    errors=['No transactions extracted from image statement'],
                )

            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                full_text = '\n'.join(
                    page.extract_text(x_tolerance=2, y_tolerance=2) or ''
                    for page in pdf.pages
                )
                if len(full_text.strip()) < 100:
                    full_text = _extract_pdf_text_with_ocr(file_bytes) or full_text

                bank = _detect_bank(full_text)
                acc_no, acc_name = _extract_metadata(full_text)

                if bank == 'DBS':
                    txns, errors = _parse_dbs(pdf)
                elif bank == 'SBI':
                    txns, errors = _parse_sbi(pdf)
                elif bank == 'HDFC':
                    txns, errors = _parse_hdfc(pdf)
                else:
                    # ICICI, AXIS, unknown — generic table parser
                    txns, errors = _parse_generic(pdf)
                    if not txns:
                        # second chance: try all specific parsers
                        for fn in [_parse_sbi, _parse_hdfc, _parse_dbs]:
                            txns, errs = fn(pdf)
                            if txns:
                                break
                        else:
                            errors.append('No transactions extracted by any parser')

                txns = _deduplicate(txns)

                ai_result = _ollama_statement_result(full_text)
                if ai_result and (
                    not txns or
                    (len(ai_result.transactions) > len(txns) and bank == 'UNKNOWN')
                ):
                    logger.info(
                        'Using Ollama statement fallback: %d transactions from %s',
                        len(ai_result.transactions),
                        ai_result.bank_name,
                    )
                    return ai_result

                logger.info('Parsed %d transactions from %s statement', len(txns), bank)

                return ParseResult(
                    bank_name=bank,
                    account_no=acc_no,
                    account_name=acc_name,
                    transactions=txns,
                    errors=errors,
                )

        except Exception as e:
            image_text = _extract_image_text(file_bytes)
            ai_result = _ollama_statement_result(image_text)
            if ai_result:
                logger.info(
                    'Parsed %d transactions from statement image fallback using Ollama',
                    len(ai_result.transactions),
                )
                return ai_result
            logger.error('PDF parsing failed: %s', e, exc_info=True)
            return ParseResult(
                bank_name='ERROR',
                account_no='',
                account_name='',
                errors=[f'PDF parsing failed: {e}'],
            )


# ─────────────────────────────────────────────────────────────────────────────
# Public API (backward-compatible)
# ─────────────────────────────────────────────────────────────────────────────

def parse_bank_statement(file_bytes: bytes, file_name: str = "") -> ParseResult:
    """Entry point called by views.py — unchanged signature."""
    return BankStatementParser().parse_pdf(file_bytes, file_name)
