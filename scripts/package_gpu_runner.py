"""Build a small pinned runner artifact locally. Does not upload or rent anything."""

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

from reconflow.benchmarks.protocol import MODELS, OPTIONS, PROTOCOL

OLLAMA = {
    "version": "0.40.16",
    "url": "https://github.com/ollama/ollama/releases/download/v0.40.16/ollama-linux-amd64.tar.zst",
    "sha256": "87bfafb2acbc89b2e6a1be0a9043de6aa75fb450696f86bc426e65fc448f788d",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a new artifact path")
    source = Path(__file__).resolve().parents[1] / "backend/reconflow/benchmarks"
    files = {
        "runner.py": (source / "runner.py").read_bytes(),
        "bootstrap.py": (source / "runner_bootstrap.py").read_bytes(),
        "manifest.json": json.dumps(
            {"protocol": PROTOCOL, "models": MODELS, "options": OPTIONS, "ollama": OLLAMA},
            sort_keys=True,
        ).encode(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 16, 0, 0, 0))
            info.external_attr = 0o600 << 16
            archive.writestr(info, content)
    print(
        json.dumps(
            {
                "path": str(args.output),
                "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
            }
        )
    )


if __name__ == "__main__":
    main()
