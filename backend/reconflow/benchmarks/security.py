import hashlib
import hmac
import re

from reconflow.config import settings


def token(value: str, purpose: str) -> str:
    return hmac.new(
        settings().session_secret.get_secret_value().encode(),
        f"gpu:{purpose}:{value}".encode(),
        hashlib.sha256,
    ).hexdigest()


def label(lease_id: str, deadline: int) -> str:
    value = f"rfb1:{lease_id}:{deadline}"
    return f"{value}:{token(value, 'label')[:24]}"


def parse_label(value: str):
    if not re.fullmatch(r"rfb1:[a-f0-9]{32}:[0-9]{10}:[a-f0-9]{24}", value):
        return None
    prefix, lease_id, deadline, mac = value.split(":")
    if not hmac.compare_digest(mac, token(f"{prefix}:{lease_id}:{deadline}", "label")[:24]):
        return None
    return lease_id, int(deadline)
