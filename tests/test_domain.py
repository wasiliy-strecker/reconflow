from decimal import Decimal

import pytest
from reconflow import fixtures
from reconflow.domain import (
    InvoiceData,
    invoice_issues,
    money,
    parse_payments,
    reconcile,
    reference_matches,
)


def invoice(
    identifier="i1", number="RE-2026-1001", amount="1190.00", currency="EUR", confirmed=True
):
    data = fixtures.invoice_data(0).model_dump(mode="json")
    data.update(invoice_number=number, gross_amount=amount, currency=currency)
    return {"id": identifier, "payload": data, "confirmed": confirmed}


def payment(identifier="p1", reference="Zahlung RE-2026-1001", amount="1190.00", currency="EUR"):
    return {
        "id": identifier,
        "reference": reference,
        "amount": amount,
        "currency": currency,
        "payer": "Nordlicht Studio",
    }


@pytest.mark.parametrize(
    "text,expected",
    [("1.190,00", "1190.00"), ("1190.00", "1190.00"), ("0,10", "0.10"), ("12", "12.00")],
)
def test_decimal_money(text, expected):
    assert money(text) == Decimal(expected)


@pytest.mark.parametrize("text", ["NaN", "Infinity", "1.001", "wat", "1e100"])
def test_invalid_money(text):
    with pytest.raises(ValueError):
        money(text)


def test_no_prefix_reference_match():
    assert not reference_matches("RE-1", "RE-10")
    assert reference_matches("RE-2026-1001", "Danke, RE 2026 1001.")


def test_exact_match():
    result = reconcile([invoice()], [payment()])
    assert result[0]["status"] == "MATCHED"
    assert result[0]["difference"] == "0.00"


@pytest.mark.parametrize(
    "number,reference",
    [
        ("RE-1", "RE-10"),
        ("RE-2026-1001", "Danke, RE20261001."),
        ("RE2026", "RE-2026"),
        ("RE-2026-1001", "RE 2026 1001"),
        ("RE_ABC", "RE-ABC"),
        ("123", "0123"),
    ],
)
def test_index_preserves_reference_semantics(number, reference):
    result = reconcile([invoice(number=number)], [payment(reference=reference)])
    actual = next(row for row in result if row["invoice_id"] == "i1")
    assert bool(actual["payment_ids"]) == reference_matches(number, reference)


def test_partial_and_multiple_partial_payments():
    assert reconcile([invoice()], [payment(amount="500")])[0]["status"] == "PARTIAL"
    result = reconcile([invoice()], [payment("p1", amount="500"), payment("p2", amount="690")])
    assert result[0]["status"] == "MATCHED"
    assert len(result[0]["payment_ids"]) == 2


def test_duplicate_payment_not_discarded():
    result = reconcile([invoice()], [payment("p1"), payment("p2")])
    assert result[0]["status"] == "DUPLICATE"
    assert result[0]["received"] == "2380.00"


def test_amount_only_requires_review():
    result = reconcile([invoice()], [payment(reference="Vielen Dank")])
    assert result[0]["status"] == "REVIEW"
    assert result[0]["candidates"] == ["i1"]
    assert result[1]["status"] == "UNMATCHED"


def test_wrong_currency_never_allocates():
    result = reconcile([invoice()], [payment(currency="USD")])
    assert result[0]["reason_code"] == "CURRENCY_MISMATCH"
    assert result[1]["payment_ids"] == []


def test_ambiguous_invoice_reference_never_allocates():
    result = reconcile([invoice("i1"), invoice("i2")], [payment()])
    assert result[0]["reason_code"] == "AMBIGUOUS_REFERENCE"
    assert all(not row["payment_ids"] for row in result[1:])


def test_unconfirmed_invoice_not_used():
    result = reconcile([invoice(confirmed=False)], [payment()])
    assert result[-1]["reason_code"] == "UNCONFIRMED_INVOICE"


def test_manual_decision_allocates_once():
    result = reconcile(
        [invoice("i1"), invoice("i2", number="OTHER")], [payment(reference="Danke")], {"p1": "i2"}
    )
    assert sum(len(row["payment_ids"]) for row in result) == 1
    assert next(r for r in result if r["invoice_id"] == "i2")["status"] == "MATCHED"
    assert next(r for r in result if r["invoice_id"] == "i2")["reason_code"] == "MANUAL_DECISION"


def test_csv_fixture_and_duplicate_ids():
    parsed, errors = parse_payments(fixtures.payment_csv())
    assert len(parsed) == 6 and not errors
    body = fixtures.payment_csv() + fixtures.payment_csv().splitlines()[1] + b"\n"
    _, errors = parse_payments(body)
    assert "mehrfach" in errors[0]["message"]


def test_csv_errors_report_lines():
    data = b"payment_id,reference,amount,currency,paid_at,payer\n1,A,NaN,EUR,2026-11-01,B\n2,B,3.00,EUR,wrong,C\n"
    parsed, errors = parse_payments(data)
    assert not parsed and [e["line"] for e in errors] == [2, 3]


def test_invoice_validation_flags_missing_and_conflicting_totals():
    assert "Rechnungsnummer fehlt." in invoice_issues(InvoiceData())
    data = fixtures.invoice_data(0).model_copy(update={"gross_amount": "1234.00"})
    assert any("Steuerbetrag" in issue for issue in invoice_issues(data))


def test_synthetic_documents_are_reproducible():
    for i in range(6):
        assert fixtures.document(i) == fixtures.document(i)
