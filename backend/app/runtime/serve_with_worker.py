"""Process supervisor: uvicorn first, then optional embedded worker (Render free)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request


def _wait_for_health(port: str, timeout_seconds: float = 90.0) -> bool:
    deadline = time.time() + timeout_seconds
    url = f"http://127.0.0.1:{port}/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if 200 <= response.status < 300:
                    return True
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(1.0)
    return False


def main() -> None:
    port = os.environ.get("PORT", "8000")
    poll = os.environ.get("PRORA_WORKER_POLL_SECONDS", "10")
    children: list[subprocess.Popen[bytes]] = []

    # La API debe escuchar antes que el worker: el health check de Render
    # solo espera 5s por respuesta y el free se satura si sklearn arranca primero.
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

    if not _wait_for_health(port):
        print("prora: ERROR — /health no respondió a tiempo", flush=True)
        api.terminate()
        sys.exit(1)
    print("prora: /health OK; arrancando worker embebido...", flush=True)

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

    def _shutdown(signum: int, _frame: object) -> None:
        print(f"prora: señal {signum}, deteniendo procesos...", flush=True)
        for proc in reversed(children):
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
