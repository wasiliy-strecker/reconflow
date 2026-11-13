"""Small opt-in live evaluation using synthetic fixtures and the real budget ledger."""

import argparse
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from reconflow import ai, fixtures
from reconflow.config import settings
from reconflow.db import transaction


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Authorize actual paid OpenAI calls")
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()
    if not args.execute:
        parser.error("Pass --execute to run paid calls against the configured ReconFlow budget.")
    results = []
    fields = [
        "invoice_number",
        "issuer",
        "customer",
        "invoice_date",
        "due_date",
        "currency",
        "net_amount",
        "tax_amount",
        "gross_amount",
    ]
    for index in [0, 1, 4, 2, 3, 5][: max(1, min(args.limit, 6))]:
        name, mime, content = fixtures.document(index)
        job = "evaluation-" + str(uuid.uuid4())
        start = time.monotonic()
        try:
            actual = ai.extract(job, content, mime, name).model_dump(mode="json")
            expected = fixtures.invoice_data(index).model_dump(mode="json")
            checks = {field: actual[field] == expected[field] for field in fields}
            row = {
                "fixture": name,
                "format": mime,
                "checks": checks,
                "expected": expected,
                "actual": actual,
                "duration_seconds": round(time.monotonic() - start, 2),
            }
            with transaction() as db:
                usage = db.one(
                    "SELECT cost_eur,input_tokens,output_tokens FROM ai_calls WHERE job_id=:job",
                    {"job": job},
                )
            row["usage"] = {key: str(value) for key, value in (usage or {}).items()}
            print(name, sum(checks.values()), "/", len(checks), "fields correct", flush=True)
        except Exception as exc:
            row = {
                "fixture": name,
                "error_type": type(exc).__name__,
                "duration_seconds": round(time.monotonic() - start, 2),
            }
            print(name, type(exc).__name__, flush=True)
        results.append(row)
    report = {
        "timestamp": datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),
        "model": settings().openai_model,
        "prompt_version": ai.PROMPT_VERSION,
        "synthetic_data_only": True,
        "scope": "Small smoke evaluation, not a real-world accuracy guarantee",
        "results": results,
    }
    target = Path("docs/evaluation/latest.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if any("error_type" in row or not all(row["checks"].values()) for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
