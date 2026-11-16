"""Standalone GPU runner: standard library only, no cloud/provider credentials."""

import hashlib
import json
import os
import queue
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

OLLAMA = "http://127.0.0.1:11434"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(url, data=None, timeout=15, headers=None):
    body = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(
        url, body, {"Content-Type": "application/json", **(headers or {})}
    )
    return urllib.request.build_opener(NoRedirect).open(request, timeout=timeout)


def ollama(path, data=None, timeout=15):
    with request_json(OLLAMA + path, data, timeout) as response:
        return json.load(response)


class Control:
    def __init__(self):
        origin = os.environ["RF_API"].rstrip("/")
        if not origin.startswith("https://"):
            raise ValueError("Runner callbacks require HTTPS")
        self.url = origin + "/api/benchmark-runner/" + os.environ["RF_LEASE"]
        self.token = os.environ["RF_TOKEN"]
        self.deadline = int(os.environ["RF_DEADLINE"])
        self.stop = threading.Event()
        self.sequence = 0
        self.reporter = ProgressReporter(self)

    def post(self, action, data=None):
        with request_json(
            self.url + "/" + action, data or {}, 10, {"Authorization": "Bearer " + self.token}
        ) as response:
            return json.load(response)

    def heartbeat(self):
        last_ok = time.monotonic()
        while not self.stop.is_set():
            try:
                self.post("heartbeat")
                last_ok = time.monotonic()
            except urllib.error.HTTPError as exc:
                if exc.code in {401, 403, 410}:
                    self.stop.set()
            except Exception:
                pass  # Missing heartbeats also trigger the independent AWS reaper.
            if time.monotonic() - last_ok > 60 or time.time() >= self.deadline:
                self.stop.set()
            self.stop.wait(10)

    def check(self):
        if self.stop.is_set() or time.time() >= self.deadline:
            raise TimeoutError("Lease ended")


def gpu_info():
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=3,
    )
    rows = result.stdout.strip().splitlines()
    if len(rows) != 1:
        raise ValueError("Exactly one GPU required")
    gpu, memory, driver = [s.strip() for s in rows[0].split(",")]
    return {"gpu": gpu, "vram_total_mib": int(memory), "driver": driver}


class Telemetry:
    def __init__(self):
        self.stop = threading.Event()
        self.memory = None
        self.utilization = None
        self.thread = threading.Thread(target=self.sample, daemon=True)

    def sample(self):
        while not self.stop.is_set():
            try:
                result = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-gpu=memory.used,utilization.gpu",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=2,
                )
                memory, utilization = [int(p.strip()) for p in result.stdout.strip().split(",")]
                self.memory = max(self.memory or 0, memory)
                self.utilization = max(self.utilization or 0, utilization)
            except (ValueError, OSError, subprocess.SubprocessError):
                pass  # Missing telemetry is null, not an invented zero.
            self.stop.wait(0.2)


class ProgressReporter:
    """Coalesce callbacks so AWS latency never blocks measured inference reads."""

    def __init__(self, control):
        self.control = control
        self.updates = queue.Queue(maxsize=1)
        threading.Thread(target=self.run, daemon=True).start()

    def submit(self, payload):
        try:
            self.updates.put_nowait(payload)
        except queue.Full:
            pass  # A later snapshot includes all output generated so far.

    def run(self):
        while not self.control.stop.is_set():
            try:
                payload = self.updates.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.control.post("progress", payload)
            except Exception:
                pass


@contextmanager
def time_limit(seconds):
    def expired(signum, frame):
        raise TimeoutError("Request deadline")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, max(0.01, seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def generate(control, job, prompt, index):
    telemetry = Telemetry()
    telemetry.thread.start()
    started = time.monotonic_ns()
    first = None
    text = ""
    final = None
    last_progress = 0
    timeout = min(int(os.environ["RF_REQUEST_SECONDS"]), control.deadline - time.time())
    try:
        with time_limit(timeout):
            with request_json(
                OLLAMA + "/api/generate",
                {
                    "model": job["model"],
                    "prompt": prompt["text"],
                    "stream": True,
                    "options": job["options"],
                    "keep_alive": "5m",
                },
                timeout=timeout,
            ) as response:
                for line in response:
                    control.check()
                    part = json.loads(line)
                    if "error" in part:
                        raise ValueError("Ollama failed")
                    chunk = part.get("response", "")
                    if chunk and first is None:
                        first = time.monotonic_ns()
                    text += chunk
                    if len(text) > 16000:
                        raise ValueError("Output limit")
                    if part.get("done"):
                        final = part
                        break
                    if time.monotonic() - last_progress >= 2:
                        last_progress = time.monotonic()
                        control.sequence += 1
                        control.reporter.submit(
                            {
                                "request_id": job["id"],
                                "sequence": control.sequence,
                                "sample": index,
                                "text": text,
                            }
                        )
            ended = time.monotonic_ns()
        if not final:
            raise ValueError("Incomplete inference response")
        loaded = ollama("/api/ps")["models"]
        model = next(m for m in loaded if m["name"] == job["model"] or m["model"] == job["model"])
        result = {
            "index": index,
            "output": text,
            "elapsed_ms": (ended - started) / 1e6,
            "ttft_ms": (first - started) / 1e6 if first else None,
            "vram_peak_mib": telemetry.memory,
            "gpu_utilization_peak": telemetry.utilization,
            "gpu_only": model.get("size", 0) > 0 and model.get("size_vram", 0) >= model["size"],
        }
        for key in (
            "eval_count",
            "eval_duration",
            "prompt_eval_count",
            "prompt_eval_duration",
            "load_duration",
        ):
            result[key] = final[key]
        result["prompt_eval_cached_count"] = final.get("prompt_eval_cached_count")
        return result
    finally:
        telemetry.stop.set()
        telemetry.thread.join(timeout=3)


def run(control):
    manifest = json.loads(Path(__file__).with_name("manifest.json").read_text())
    model = os.environ["RF_MODEL"]
    expected = manifest["models"][model]
    started = time.monotonic()
    # A strict whole-startup deadline, not just a timeout between download bytes.
    with time_limit(min(int(os.environ["RF_STARTUP_SECONDS"]), control.deadline - time.time())):
        # Detect moved tags before downloading weights, then verify locally too.
        repository, tag = model.split(":", 1)
        with urllib.request.urlopen(
            f"https://registry.ollama.ai/v2/library/{repository}/manifests/{tag}", timeout=15
        ) as response:
            if hashlib.sha256(response.read(1024 * 1024)).hexdigest() != expected["digest"]:
                raise ValueError("Remote model digest changed")
        ollama("/api/pull", {"model": model, "stream": False}, timeout=600)
        download_ms = (time.monotonic() - started) * 1000
        tags = ollama("/api/tags")["models"]
        actual = next(m for m in tags if m["name"] == model)
        if actual["digest"].removeprefix("sha256:") != expected["digest"]:
            raise ValueError("Model digest changed")
        before_load = time.monotonic()
        ollama(
            "/api/generate",
            {
                "model": model,
                "prompt": "",
                "stream": False,
                "keep_alive": "5m",
                "options": manifest["options"],
            },
            timeout=600,
        )
        metadata = {
            **gpu_info(),
            "model_digest": expected["digest"],
            "quantization": actual["details"]["quantization_level"],
            "runtime_version": ollama("/api/version")["version"],
            "download_ms": download_ms,
            "load_ms": (time.monotonic() - before_load) * 1000,
        }
        if metadata["runtime_version"] != manifest["ollama"]["version"]:
            raise ValueError("Unexpected runtime version")
        control.post("ready", metadata)
    journal = Path(__file__).with_name("claimed.json")
    # A restarted runner never replays an uncertain inference.
    if journal.exists():
        raise ValueError("Runner restarted with an existing claim")
    while not control.stop.wait(2):
        control.check()
        job = control.post("poll")["request"]  # No retry of an ambiguous claim.
        if not job:
            continue
        journal.write_text(json.dumps({"id": job["id"]}))
        samples = [generate(control, job, p, i) for i, p in enumerate(job["prompts"])]
        payload = {"request_id": job["id"], "samples": samples}
        for attempt in range(3):
            try:
                control.post("complete", payload)  # Result delivery is idempotent.
                break
            except (OSError, urllib.error.URLError):
                if attempt == 2:
                    raise
                control.stop.wait(2)
        journal.unlink()


def main():
    control = Control()
    threading.Thread(target=control.heartbeat, daemon=True).start()
    try:
        run(control)
    except Exception:
        try:
            control.post("failed", {"code": "inference_failed"})
        except Exception:
            pass  # Independent reaper still owns destruction.
        raise SystemExit("GPU runner stopped; inspect the lease status") from None
    finally:
        control.stop.set()


if __name__ == "__main__":
    main()
