import json
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class OllamaExtractionError(Exception):
    pass


def _enabled() -> bool:
    return bool(getattr(settings, "OLLAMA_ENABLED", True))


def _call_ollama(prompt: str, *, temperature: float = 0.0) -> Dict[str, Any]:
    if not _enabled():
        raise OllamaExtractionError("Ollama extraction is disabled")

    base_url = getattr(settings, "OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = getattr(settings, "OLLAMA_MODEL", "llama3.1:8b")
    timeout = getattr(settings, "OLLAMA_TIMEOUT", 120)

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": temperature,
            "num_predict": 4096,
        },
    }

    try:
        response = requests.post(f"{base_url}/api/generate", json=payload, timeout=timeout)
        response.raise_for_status()
        raw = response.json().get("response", "")
        return _load_json(raw)
    except requests.RequestException as exc:
        raise OllamaExtractionError(f"Ollama request failed: {exc}") from exc


def _load_json(raw: str) -> Dict[str, Any]:
    if not raw:
        raise OllamaExtractionError("Ollama returned an empty response")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            raise OllamaExtractionError("Ollama did not return JSON")
        return json.loads(match.group(0))


def _clean_text(text: str, max_chars: int = 60000) -> str:
    text = re.sub(r"[ \t]+", " ", text or "")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars // 2] + "\n\n...[middle truncated]...\n\n" + text[-max_chars // 2 :]


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    cleaned = re.sub(r"[₹$,\s]", "", str(value).strip())
    cleaned = cleaned.replace("CR", "").replace("DR", "")
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _to_date(value: Any) -> Optional[str]:
    if not value:
        return None
    raw = str(value).strip()
    formats = [
        "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y",
        "%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%d %b %y",
        "%d.%m.%Y", "%d.%m.%y", "%b %d, %Y", "%B %d, %Y", "%d %B %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def extract_receipt_fields(text: str, file_name: str = "") -> Dict[str, Any]:
    prompt = f"""
You are a careful financial document extraction engine.
Extract fields from Indian receipts, invoices, payment vouchers, and billing documents.
Return only valid JSON with this schema:
{{
  "receipt_no": "string or empty",
  "receipt_date": "YYYY-MM-DD or null",
  "amount": "final payable amount as number string or null",
  "confidence": 0-100,
  "reason": "short reason"
}}

Rules:
- Pick the final/grand/net payable amount, not GST, subtotal, taxable value, round off, TDS, discount, freight, or item rate.
- If multiple totals exist, choose the amount the customer actually paid or must pay.
- If both numeric and words amounts exist, prefer the numeric final payable total.
- Dates must be normalized to YYYY-MM-DD.
- Do not invent values. Use null or empty string when unclear.

File name: {file_name}
Extracted text:
{_clean_text(text)}
"""
    data = _call_ollama(prompt)
    return {
        "receipt_no": str(data.get("receipt_no") or "").strip(),
        "receipt_date": _to_date(data.get("receipt_date")),
        "amount": _to_decimal(data.get("amount")),
        "confidence": float(data.get("confidence") or 0),
        "reason": str(data.get("reason") or "").strip(),
    }


def extract_statement_transactions(text: str) -> Dict[str, Any]:
    prompt = f"""
You are a careful financial bank statement extraction engine.
Extract transactions from raw text produced from a bank statement PDF, Excel workbook, or OCR image.
Return only valid JSON with this schema:
{{
  "bank_name": "DBS/SBI/HDFC/ICICI/AXIS/UNKNOWN",
  "account_no": "string or empty",
  "account_name": "string or empty",
  "transactions": [
    {{
      "txn_date": "YYYY-MM-DD",
      "value_date": "YYYY-MM-DD or null",
      "description": "narration",
      "ref_no": "reference/cheque/UTR or empty",
      "utr_no": "UTR or empty",
      "txn_type": "debit or credit",
      "amount": "positive number string",
      "balance": "number string or null"
    }}
  ],
  "confidence": 0-100,
  "reason": "short reason"
}}

Rules:
- Extract transaction rows only. Ignore opening balance, closing balance summaries, headers, and totals.
- Amount must be positive and txn_type must say whether it is debit or credit.
- If the source has separate debit/withdrawal and credit/deposit columns, use the populated column to set txn_type.
- If the source has one amount column with DR/CR markers, use DR as debit and CR as credit.
- Balance may be negative for OD/CC accounts.
- Dates must be normalized to YYYY-MM-DD.
- Do not invent missing transactions.
- Preserve row order from the source.

Extracted text:
{_clean_text(text)}
"""
    data = _call_ollama(prompt)
    transactions: List[Dict[str, Any]] = []
    for item in data.get("transactions") or []:
        amount = _to_decimal(item.get("amount"))
        txn_date = _to_date(item.get("txn_date"))
        txn_type = str(item.get("txn_type") or "").lower().strip()
        if not amount or not txn_date or txn_type not in {"debit", "credit"}:
            continue
        transactions.append({
            "txn_date": txn_date,
            "value_date": _to_date(item.get("value_date")),
            "description": str(item.get("description") or "").strip(),
            "ref_no": str(item.get("ref_no") or "").strip(),
            "utr_no": str(item.get("utr_no") or "").strip(),
            "txn_type": txn_type,
            "amount": amount,
            "balance": _to_decimal(item.get("balance")),
        })

    return {
        "bank_name": str(data.get("bank_name") or "UNKNOWN").strip() or "UNKNOWN",
        "account_no": str(data.get("account_no") or "").strip(),
        "account_name": str(data.get("account_name") or "").strip(),
        "transactions": transactions,
        "confidence": float(data.get("confidence") or 0),
        "reason": str(data.get("reason") or "").strip(),
    }
