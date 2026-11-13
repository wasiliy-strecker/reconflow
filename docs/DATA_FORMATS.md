# Import formats

All CSV files use UTF-8, optionally with BOM, and comma or semicolon separators.
Use ISO dates (`YYYY-MM-DD`). Decimal strings may use `1190.00` or German `1.190,00`.
Quote comma-containing values in comma-separated CSV. Never use floating-point
rounding to repair inconsistent source data. Validation errors identify source lines;
an invalid import inserts no rows.

## Payment CSV

```csv
payment_id,reference,amount,currency,paid_at,payer
PAY-001,Zahlung RE-2026-1001,1190.00,EUR,2026-11-09,Nordlicht Studio
```

All six columns are required. `payment_id` is stable and unique within the session.
Repeating the same file is harmless. Reusing an ID with different values rejects the
import. Distinct IDs are retained even for equal amounts, so possible double payments
are visible. Only positive incoming payments in EUR, USD, GBP or CHF are supported.
Download the complete fixture from `/api/examples-payments`.

## Invoice CSV (local mode)

```csv
invoice_number,issuer,customer,invoice_date,due_date,currency,net_amount,tax_amount,gross_amount
RE-2026-1001,Form & Funktion Musteragentur,Nordlicht Studio,2026-11-02,2026-11-16,EUR,1000.00,190.00,1190.00
```

Required columns: invoice_number, issuer, customer, invoice_date, currency, gross_amount.
Imported invoices remain unconfirmed. Empty optional fields become null. The UI
requires confirmation before any automatic allocation.

## Document input

PDF, JPEG or PNG; maximum 4 MiB; PDF 1–5 pages, unencrypted; images maximum 20 megapixels.
The API verifies actual content rather than trusting the extension. Upload does not
itself send data to OpenAI. The separate extraction action sends inline document data
to the configured model with a strict structured-output schema.

Public demo mode permits only byte-identical generated fixtures. Local mode permits
arbitrary supported files. This restriction is enforced on the backend.

## Matching rules

Only a unique confirmed invoice reference and equal currency allocate a payment
automatically. Reference separators are tolerated, but RE-1 does not match RE-10.
Multiple referenced payments are summed with Decimal. An amount-only match remains a
review candidate. Ambiguous references, currency differences, excess amounts and
possible duplicate payments remain visible. Manual decisions are version checked,
audited and included in subsequent runs. One payment is never allocated twice.

XLSX contains Abgleich, Rechnungen, Zahlungen and Importe. Amounts are exact decimal
strings, and all source text is stored as text rather than spreadsheet formulas.
