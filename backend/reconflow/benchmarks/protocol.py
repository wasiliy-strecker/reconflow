"""Versioned, synthetic workloads. No network or database access."""

import hashlib
from decimal import Decimal

PROTOCOL = "reconflow-text-v1"
OPTIONS = {"num_ctx": 4096, "num_predict": 512, "temperature": 0, "seed": 42}
MODELS = {
    "gemma3:4b-it-q4_K_M": {"min_vram_mib": 8192, "quantization": "Q4_K_M"},
    "gemma3:12b-it-q4_K_M": {"min_vram_mib": 16384, "quantization": "Q4_K_M"},
}
PROMPTS = [
    {
        "id": "explain",
        "text": "Erkläre einer Schülerin in fünf Sätzen, wie ein Regenbogen entsteht.",
    },
    {
        "id": "summarize",
        "text": "Fasse in drei Stichpunkten zusammen: Die fiktive Stadt Lindenhafen eröffnet eine Bibliothek. Sie hat dienstags bis samstags geöffnet. Kinder können kostenlos Bücher ausleihen. Ein Leseklub trifft sich jeden Freitag.",
    },
    {
        "id": "code",
        "text": "Schreibe eine Python-Funktion, die eine Liste von ganzen Zahlen stabil dedupliziert. Erkläre kurz die Laufzeit und gib ein Beispiel.",
    },
    {
        "id": "reason",
        "text": "In einem fiktiven Garten stehen drei Reihen mit je sieben Bäumen. Vier weitere werden gepflanzt, zwei entfernt. Erkläre die Rechnung und nenne die verbleibende Anzahl.",
    },
    {
        "id": "write",
        "text": "Schreibe eine kurze freundliche Einladung zum fiktiven Roboter-Basteltag in Lindenhafen. Erfinde keine Kontaktangaben. Verwende höchstens 120 Wörter.",
    },
]


def workload(ids: list[str] | None = None, custom: list[str] | None = None):
    if custom is not None:
        return [{"id": "private", "text": p} for p in custom]
    index = {p["id"]: p for p in PROMPTS}
    if not ids or any(i not in index for i in ids):
        raise ValueError("Bitte vorbereitete Prompts auswählen.")
    return [dict(index[i]) for i in ids]


def suite():
    return [{**PROMPTS[0], "warmup": True}] + [dict(p) for _ in range(3) for p in PROMPTS]


def decimal(value) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError("Ungültige Preisangabe.")
    return result


def estimate(offer: dict, seconds: int, config) -> Decimal:
    # dph_total is the provider's price for the requested allocated storage.
    # Add explicit bounded transfer allowances and two minutes of cleanup time.
    hourly = decimal(offer["hourly_usd"])
    transfers = decimal(offer["download_usd_gb"]) * config.gpu_download_gb
    transfers += decimal(offer["upload_usd_gb"]) * config.gpu_upload_gb
    return ((hourly * Decimal(seconds + 120) / 3600 + transfers) * config.gpu_usd_to_eur).quantize(
        Decimal("0.00000001")
    )


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
