"""Entirely synthetic, reproducible invoice documents and ground-truth data."""

import csv
import io
from datetime import date
from decimal import Decimal
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.colors import HexColor
from reportlab.pdfgen.canvas import Canvas

from reconflow.domain import InvoiceData, LineItem

SPECS = [
    (
        "RE-2026-1001",
        "Nordlicht Studio",
        "1190.00",
        "1000.00",
        "190.00",
        "Website-Konzeption",
        "pdf",
    ),
    ("RE-2026-1002", "Atelier Morgenrot", "595.00", "500.00", "95.00", "Markenworkshop", "png"),
    ("RE-2026-1003", "Linden & Partner", "2380.00", "2000.00", "380.00", "Webentwicklung", "pdf"),
    ("RE-2026-1004", "Kollektiv West", "357.00", "300.00", "57.00", "Design-Beratung", "pdf"),
    ("RE-2026-1005", "Mira Kunsthandel", "833.00", "700.00", "133.00", "Shop-Erweiterung", "jpg"),
    ("RE-2026-1006", "Hafenwerk Digital", "476.00", "400.00", "76.00", "Content-Konzeption", "pdf"),
]


def invoice_data(index: int) -> InvoiceData:
    number, customer, gross, net, tax, description, _ = SPECS[index]
    return InvoiceData(
        invoice_number=number,
        issuer="Form & Funktion Musteragentur",
        customer=customer,
        invoice_date=date(2026, 11, 2),
        due_date=date(2026, 11, 16),
        currency="EUR",
        net_amount=net,
        tax_amount=tax,
        gross_amount=gross,
        line_items=[LineItem(description=description, quantity="1", amount=net)],
    )


def eur(value):
    return f"{Decimal(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " EUR"


@lru_cache
def document(index: int):
    data = invoice_data(index)
    ext = SPECS[index][-1]
    output = io.BytesIO()
    lines = [
        "Form & Funktion Musteragentur",
        "Musterstrasse 12, 10115 Berlin",
        "SYNTHETISCHE BEISPIELRECHNUNG",
        "",
        "RECHNUNG " + data.invoice_number,
        "Rechnung an: " + data.customer,
        "Rechnungsdatum: 02.11.2026",
        "Faellig am: 16.11.2026",
        "",
        data.line_items[0].description + " (Menge: 1)",
        "Netto: " + eur(data.net_amount),
        "Umsatzsteuer 19 %: " + eur(data.tax_amount),
        "Gesamtbetrag: " + eur(data.gross_amount),
        "",
        "Verwendungszweck: " + data.invoice_number,
        "Keine Zahlung ausloesen. Ausschliesslich Testdaten.",
    ]
    if ext == "pdf":
        canvas = Canvas(output, pagesize=(595, 842), invariant=1)
        canvas.setFillColor(HexColor("#143d35"))
        canvas.rect(0, 748, 595, 94, fill=1, stroke=0)
        canvas.setFillColor(HexColor("#ffffff"))
        canvas.setFont("Helvetica-Bold", 25)
        canvas.drawString(45, 785, "Form & Funktion")
        canvas.setFillColor(HexColor("#263b34"))
        for n, text in enumerate(lines):
            canvas.setFont("Helvetica-Bold" if n in [4, 12] else "Helvetica", 16 if n == 4 else 11)
            canvas.drawString(45, 705 - n * 31, text)
        canvas.save()
        mime = "application/pdf"
    else:
        image = Image.new("RGB", (1100, 1500), "#faf9f5")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=26)
        title = ImageFont.load_default(size=40)
        draw.rectangle((0, 0, 1100, 160), fill="#143d35")
        draw.text((70, 60), "Form & Funktion", font=title, fill="white")
        for n, text in enumerate(lines):
            draw.text((70, 225 + n * 65), text, font=font, fill="#263b34")
        image.save(output, format="PNG" if ext == "png" else "JPEG")
        mime = "image/png" if ext == "png" else "image/jpeg"
    return data.invoice_number + "." + ext, mime, output.getvalue()


def payment_csv():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["payment_id", "reference", "amount", "currency", "paid_at", "payer"])
    for row in [
        ["PAY-001", "Rechnung RE-2026-1001", "1190.00", "EUR", "2026-11-05", "Nordlicht Studio"],
        ["PAY-002", "RE-2026-1002", "595.00", "EUR", "2026-11-05", "Atelier Morgenrot"],
        ["PAY-003", "Anzahlung RE-2026-1003", "1000.00", "EUR", "2026-11-06", "Linden & Partner"],
        ["PAY-004", "RE-2026-1004", "357.00", "EUR", "2026-11-06", "Kollektiv West"],
        ["PAY-005", "RE-2026-1004", "357.00", "EUR", "2026-11-07", "Kollektiv West"],
        [
            "PAY-006",
            "Vielen Dank fuer das Projekt",
            "833.00",
            "EUR",
            "2026-11-08",
            "Mira Kunsthandel",
        ],
    ]:
        writer.writerow(row)
    return output.getvalue().encode()
