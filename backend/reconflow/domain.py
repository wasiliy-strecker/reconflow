"""Pure, deterministic domain logic. No SDK, HTTP or database dependencies."""

import csv
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LineItem(BaseModel):
    description: str = Field(max_length=300)
    quantity: str | None = None
    amount: str | None = None


class Evidence(BaseModel):
    field: str
    page: int | None = None
    text: str = Field(max_length=500)


class InvoiceData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invoice_number: str | None = Field(default=None, max_length=120)
    issuer: str | None = Field(default=None, max_length=200)
    customer: str | None = Field(default=None, max_length=200)
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str | None = Field(default=None, max_length=3)
    net_amount: str | None = None
    tax_amount: str | None = None
    gross_amount: str | None = None
    line_items: list[LineItem] = Field(default_factory=list, max_length=100)
    warnings: list[str] = Field(default_factory=list, max_length=20)
    evidence: list[Evidence] = Field(default_factory=list, max_length=30)

    @field_validator("net_amount", "tax_amount", "gross_amount")
    @classmethod
    def amounts(cls, value):
        return str(money(value)) if value is not None else None

    @field_validator("currency")
    @classmethod
    def currencies(cls, value):
        if value is None:
            return None
        if value.upper() not in {"EUR", "USD", "GBP", "CHF"}:
            raise ValueError("Unterstützte Währungen: EUR, USD, GBP, CHF")
        return value.upper()


class Suggestion(BaseModel):
    invoice_id: str | None
    reason: str = Field(max_length=1000)


class MatchResult(BaseModel):
    invoice_id: str | None
    invoice_number: str | None
    customer: str
    status: Literal["MATCHED", "PARTIAL", "REVIEW", "UNMATCHED", "DUPLICATE"]
    reason_code: str
    reason: str
    payment_ids: list[str]
    expected: str
    received: str
    difference: str
    currency: str
    candidates: list[str] = Field(default_factory=list)


def money(value) -> Decimal:
    text = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Ungültiger Betrag") from exc
    if not amount.is_finite() or abs(amount) >= Decimal("1000000000000000"):
        raise ValueError("Ungültiger Betrag")
    if amount != amount.quantize(Decimal("0.01")):
        raise ValueError("Beträge benötigen höchstens zwei Nachkommastellen")
    return amount.quantize(Decimal("0.01"))


def invoice_issues(data: InvoiceData) -> list[str]:
    issues = []
    for field, label in [
        ("invoice_number", "Rechnungsnummer"),
        ("issuer", "Aussteller"),
        ("customer", "Kunde"),
        ("invoice_date", "Rechnungsdatum"),
        ("currency", "Währung"),
        ("gross_amount", "Bruttobetrag"),
    ]:
        if not getattr(data, field):
            issues.append(f"{label} fehlt.")
    if data.gross_amount is not None and money(data.gross_amount) <= 0:
        issues.append("Der Bruttobetrag muss positiv sein. Gutschriften folgen später.")
    if all(v is not None for v in [data.net_amount, data.tax_amount, data.gross_amount]):
        if money(data.net_amount) + money(data.tax_amount) != money(data.gross_amount):
            issues.append("Netto- und Steuerbetrag ergeben nicht den Bruttobetrag.")
    if data.invoice_date and data.due_date and data.due_date < data.invoice_date:
        issues.append("Die Fälligkeit liegt vor dem Rechnungsdatum.")
    return issues


def read_csv(content: bytes, required: set[str], limit=10000):
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Bitte eine UTF-8-kodierte CSV verwenden.") from exc
    if not text.strip():
        raise ValueError("Die CSV ist leer.")
    delimiter = ";" if text.splitlines()[0].count(";") > text.splitlines()[0].count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("Benötigte Spalten: " + ", ".join(sorted(required)))
    rows, errors = [], []
    for line, row in enumerate(reader, 2):
        if line > limit + 1:
            raise ValueError(f"Höchstens {limit} Zeilen sind erlaubt.")
        if None in row or any(value is None for value in row.values()):
            errors.append({"line": line, "message": "Die Anzahl der Spalten stimmt nicht."})
        else:
            rows.append((line, row))
    return rows, errors


def parse_payments(content: bytes, limit=10000):
    rows, errors = read_csv(
        content, {"payment_id", "reference", "amount", "currency", "paid_at", "payer"}, limit
    )
    payments, seen = [], set()
    for line, row in rows:
        try:
            external_id = row["payment_id"].strip()
            if not external_id or len(external_id) > 150:
                raise ValueError("payment_id fehlt oder ist zu lang.")
            if external_id in seen:
                raise ValueError("payment_id kommt mehrfach in dieser Datei vor.")
            amount = money(row["amount"])
            if amount <= 0:
                raise ValueError("Nur positive Zahlungseingänge werden unterstützt.")
            currency = row["currency"].strip().upper()
            if currency not in {"EUR", "USD", "GBP", "CHF"}:
                raise ValueError("Währung wird nicht unterstützt.")
            paid_at = date.fromisoformat(row["paid_at"].strip())
            if len(row["reference"]) > 500 or len(row["payer"]) > 200:
                raise ValueError("Verwendungszweck oder Name ist zu lang.")
            payments.append(
                {
                    "external_id": external_id,
                    "reference": row["reference"].strip(),
                    "amount": str(amount),
                    "currency": currency,
                    "paid_at": str(paid_at),
                    "payer": row["payer"].strip(),
                }
            )
            seen.add(external_id)
        except (ValueError, InvalidOperation) as exc:
            errors.append({"line": line, "message": str(exc)})
    return payments, errors


def reference_matches(number: str, reference: str) -> bool:
    parts = re.findall(r"[A-Z0-9]+", number.upper())
    if not parts:
        return False
    pattern = r"(?<![A-Z0-9])" + r"[\W_]*".join(map(re.escape, parts)) + r"(?![A-Z0-9])"
    return bool(re.search(pattern, reference.upper()))


def reconcile(invoices: list[dict], payments: list[dict], decisions: dict | None = None):
    """Only explicit unambiguous references (or confirmed decisions) allocate payments.

    Amount/name similarity only produces review candidates. One payment cannot be
    allocated twice. Multiple referenced payments may settle one invoice.
    """
    decisions = decisions or {}
    results, assigned = [], {}
    valid = {row["id"]: row for row in invoices if row["confirmed"]}
    references, amounts = {}, {}
    for row in valid.values():
        data = row["payload"]
        key = "".join(re.findall(r"[A-Z0-9]+", (data.get("invoice_number") or "").upper()))
        if key:
            references.setdefault(key, []).append(row)
        amounts.setdefault((data["currency"], money(data["gross_amount"])), []).append(row)
    longest = max(map(len, references), default=0)
    for payment in payments:
        possible = {}
        tokens = re.findall(r"[A-Z0-9]+", payment["reference"].upper())
        for start in range(len(tokens)):
            key = ""
            for token in tokens[start:]:
                key += token
                if len(key) > longest:
                    break
                for row in references.get(key, []):
                    if reference_matches(row["payload"]["invoice_number"], payment["reference"]):
                        possible[row["id"]] = row
        candidates = list(possible.values())
        manual = decisions.get(payment["id"])
        if manual in valid:
            candidates = [valid[manual]]
        if len(candidates) == 1 and candidates[0]["payload"]["currency"] == payment["currency"]:
            assigned.setdefault(candidates[0]["id"], []).append(payment)
            continue
        reason_code = "AMBIGUOUS_REFERENCE" if len(candidates) > 1 else "NO_REFERENCE"
        reason = (
            "Mehrere Rechnungen passen zur Referenz."
            if len(candidates) > 1
            else "Keine eindeutige Rechnungsreferenz."
        )
        if len(candidates) == 1:
            reason_code, reason = "CURRENCY_MISMATCH", "Referenz passt, aber die Währung weicht ab."
        if not candidates:
            candidates = amounts.get((payment["currency"], money(payment["amount"])), [])
        results.append(
            MatchResult(
                invoice_id=None,
                invoice_number=None,
                customer=payment["payer"],
                status="REVIEW" if candidates else "UNMATCHED",
                reason_code=reason_code,
                reason=reason,
                payment_ids=[payment["id"]],
                expected="0.00",
                received=str(money(payment["amount"])),
                difference=str(money(payment["amount"])),
                currency=payment["currency"],
                candidates=[row["id"] for row in candidates],
            )
        )
    for invoice in invoices:
        data = invoice["payload"]
        linked = assigned.get(invoice["id"], [])
        expected = money(data["gross_amount"]) if data.get("gross_amount") else Decimal("0.00")
        received = sum((money(p["amount"]) for p in linked), Decimal("0.00"))
        status, code, reason = "UNMATCHED", "NO_PAYMENT", "Noch kein Zahlungseingang zugeordnet."
        if not invoice["confirmed"]:
            status, code, reason = (
                "REVIEW",
                "UNCONFIRMED_INVOICE",
                "Erkannte Rechnungsdaten zuerst prüfen und bestätigen.",
            )
        elif linked:
            if received == expected:
                status, code, reason = (
                    "MATCHED",
                    "REFERENCE_AMOUNT_CURRENCY",
                    "Referenz, Gesamtbetrag und Währung stimmen überein.",
                )
                if any(decisions.get(p["id"]) == invoice["id"] for p in linked):
                    code = "MANUAL_DECISION"
                    reason = (
                        "Vom Benutzer bestätigte Zuordnung. Betrag und Währung stimmen überein."
                    )
            elif received < expected:
                status, code, reason = (
                    "PARTIAL",
                    "PARTIAL_PAYMENT",
                    "Teilzahlung. Ein Restbetrag ist noch offen.",
                )
            elif len(linked) > 1 and any(money(p["amount"]) == expected for p in linked):
                status, code, reason = (
                    "DUPLICATE",
                    "POSSIBLE_DUPLICATE_PAYMENT",
                    "Mehrfacher Zahlungseingang. Bitte auf Doppelzahlung prüfen.",
                )
            else:
                status, code, reason = (
                    "REVIEW",
                    "AMOUNT_MISMATCH",
                    "Der zugeordnete Betrag übersteigt die Rechnung.",
                )
        results.append(
            MatchResult(
                invoice_id=invoice["id"],
                invoice_number=data.get("invoice_number"),
                customer=data.get("customer") or "Unbekannter Kunde",
                status=status,
                reason_code=code,
                reason=reason,
                payment_ids=[p["id"] for p in linked],
                expected=str(expected),
                received=str(received),
                difference=str(received - expected),
                currency=data.get("currency") or "EUR",
            )
        )
    return [result.model_dump() for result in results]
