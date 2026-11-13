"""Create a private local configuration without overwriting existing credentials."""

import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / ".env"
template = (
    (root / ".env.example")
    .read_text()
    .replace("replace-with-at-least-32-random-characters", secrets.token_urlsafe(48))
)
try:
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    print("Existing .env preserved.")
else:
    with os.fdopen(fd, "w") as handle:
        handle.write(template)
    print("Created private .env. Add OPENAI_API_KEY locally to enable AI.")
