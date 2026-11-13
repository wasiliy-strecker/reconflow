"""Reproducible engine-only benchmark; no database, network or paid calls."""

import json
import platform
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from reconflow.domain import reconcile


def main():
    count = 50000
    invoices = [
        {
            "id": f"i{i}",
            "confirmed": True,
            "payload": {
                "invoice_number": f"BENCH-{i:06}",
                "customer": f"Fixture {i}",
                "currency": "EUR",
                "gross_amount": "123.45",
            },
        }
        for i in range(count)
    ]
    payments = [
        {
            "id": f"p{i}",
            "reference": f"Zahlung BENCH-{i:06}",
            "amount": "123.45",
            "currency": "EUR",
            "payer": f"Fixture {i}",
        }
        for i in range(count)
    ]
    start = time.perf_counter()
    result = reconcile(invoices, payments)
    elapsed = time.perf_counter() - start
    assert len(result) == count and all(row["status"] == "MATCHED" for row in result)
    report = {
        "timestamp": datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "invoices": count,
        "payments": count,
        "duration_seconds": round(elapsed, 3),
        "scope": "Pure deterministic engine, synthetic unique references; excludes I/O, database, API and AI. Not an end-to-end SLA.",
    }
    Path("docs/evaluation/benchmark.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
