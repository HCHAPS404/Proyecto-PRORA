"""Process supervisor: uvicorn + optional embedded worker (Render free)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time


def main() -> None:
    port = os.environ.get("PORT", "8000")
    poll = os.environ.get("PRORA_WORKER_POLL_SECONDS", "10")
    children: list[subprocess.Popen[bytes]] = []

    worker = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "app.jobs.worker",
            "--poll-seconds",
            poll,
        ]
    )
    children.append(worker)
    print(f"prora: worker pid={worker.pid}", flush=True)

    api = subprocess.Popen(
        [
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            port,
            "--proxy-headers",
            "--forwarded-allow-ips=*",
        ]
    )
    children.append(api)
    print(f"prora: uvicorn pid={api.pid}", flush=True)

    def _shutdown(signum: int, _frame: object) -> None:
        print(f"prora: señal {signum}, deteniendo procesos...", flush=True)
        for proc in children:
            if proc.poll() is None:
                proc.send_signal(signum)
        deadline = time.time() + 25
        for proc in children:
            remaining = max(0.1, deadline - time.time())
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    exit_code = api.wait()
    if worker.poll() is None:
        worker.terminate()
        try:
            worker.wait(timeout=10)
        except subprocess.TimeoutExpired:
            worker.kill()
    sys.exit(exit_code if exit_code is not None else 1)


if __name__ == "__main__":
    main()
