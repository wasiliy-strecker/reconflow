"""Included as bootstrap.py in the signed runner ZIP; executes only on Vast."""

import hashlib
import json
import os
import subprocess
import tarfile
import threading
import time
import urllib.request
from pathlib import Path

from runner import Control, ollama


def main():
    control = Control()
    threading.Thread(target=control.heartbeat, daemon=True).start()
    root = Path(__file__).parent
    manifest = json.loads((root / "manifest.json").read_text())
    archive = root / "ollama.tar.zst"
    daemon = None
    started = time.monotonic()
    startup = int(os.environ["RF_STARTUP_SECONDS"])
    try:
        hasher = hashlib.sha256()
        length = 0
        with (
            urllib.request.urlopen(manifest["ollama"]["url"], timeout=30) as response,
            archive.open("wb") as output,
        ):
            while chunk := response.read(1024 * 1024):
                control.check()
                if time.monotonic() - started > startup:
                    raise TimeoutError("Startup deadline")
                length += len(chunk)
                if length > 4 * 1024**3:
                    raise ValueError("Archive too large")
                hasher.update(chunk)
                output.write(chunk)
        if hasher.hexdigest() != manifest["ollama"]["sha256"]:
            raise ValueError("Ollama checksum mismatch")
        # The separately pinned runner image uses Python 3.14's standard library.
        # The AWS application remains on Python 3.12.
        from compression import zstd

        with zstd.open(archive, "rb") as source, tarfile.open(fileobj=source, mode="r|") as tar:
            tar.extractall(root, filter="data")
        archive.unlink()
        env = {
            **os.environ,
            "OLLAMA_HOST": "127.0.0.1:11434",
            "OLLAMA_MODELS": str(root / "models"),
            "OLLAMA_NO_CLOUD": "1",
            "OLLAMA_NUM_PARALLEL": "1",
            "OLLAMA_MAX_LOADED_MODELS": "1",
            "LD_LIBRARY_PATH": str(root / "lib" / "ollama"),
        }
        daemon = subprocess.Popen(
            [str(root / "bin" / "ollama"), "serve"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(30):
            control.check()
            try:
                ollama("/api/version")
                break
            except Exception:
                time.sleep(1)
        remaining = min(
            startup - int(time.monotonic() - started), int(control.deadline - time.time())
        )
        if remaining <= 0:
            raise TimeoutError("Startup deadline")
        env["RF_STARTUP_SECONDS"] = str(remaining)
        # Main runner owns heartbeats from here. The outer timeout also kills a
        # runner that hangs while its main Python thread cannot enforce a deadline.
        control.stop.set()
        subprocess.run(
            ["python3", str(root / "runner.py")],
            env=env,
            check=True,
            timeout=max(1, control.deadline - time.time()),
        )
    except Exception:
        try:
            control.post("failed", {"code": "startup_failed"})
        except Exception:
            pass
        raise SystemExit("GPU bootstrap failed; automatic cleanup remains active") from None
    finally:
        control.stop.set()
        if daemon is not None:
            daemon.terminate()


if __name__ == "__main__":
    main()
