"""Process-level tests of hfdns-lb: CLI contract, exit codes, admin endpoint, logs, shutdown."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

EXIT_OK, EXIT_RUNTIME, EXIT_USAGE, EXIT_CONFIG = 0, 1, 2, 3


def run(binary: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(binary), *args],
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, **(env or {})},
        check=False,
    )


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def write_config(tmp_path: Path, admin_port: int, listener_port: int = 15353) -> Path:
    cfg = tmp_path / "lb.yaml"
    cfg.write_text(
        f"""
listeners:
  - {{ address: 127.0.0.1, port: {listener_port} }}
workers: 1
admin: {{ address: 127.0.0.1, port: {admin_port} }}
backends:
  - {{ name: a, address: 127.0.0.1, port: 5401, site: india }}
"""
    )
    return cfg


def test_version(lb_binary: Path) -> None:
    res = run(lb_binary, "--version")
    assert res.returncode == EXIT_OK
    assert res.stdout.startswith("hfdns-lb ")


def test_check_config_accepts_repo_dev_config(lb_binary: Path, repo_config_dir: Path) -> None:
    res = run(lb_binary, "--check-config", "--config", str(repo_config_dir / "dev.yaml"))
    assert res.returncode == EXIT_OK, res.stderr
    assert "4 backend(s)" in res.stdout


def test_check_config_reports_every_error(lb_binary: Path, tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "listeners:\n  - { address: 127.0.0.1, port: 0 }\n"
        "backends:\n  - { name: a, address: nope, site: s }\n"
        "polcy: x\n"
    )
    res = run(lb_binary, "--check-config", "-c", str(bad))
    assert res.returncode == EXIT_CONFIG
    assert "configuration has 3 error(s)" in res.stderr
    for fragment in (
        "listeners[0].port (line 2)",
        "backends[0].address (line 4)",
        "polcy (line 5)",
    ):
        assert fragment in res.stderr


@pytest.mark.parametrize(
    ("args", "code"),
    [
        (["--bogus"], EXIT_USAGE),
        ([], EXIT_USAGE),
        (["-c", "/nonexistent.yaml"], EXIT_RUNTIME),
    ],
)
def test_exit_codes(lb_binary: Path, args: list[str], code: int) -> None:
    assert run(lb_binary, *args).returncode == code


def test_invalid_log_level_env_is_rejected(lb_binary: Path, tmp_path: Path) -> None:
    cfg = write_config(tmp_path, free_port())
    res = run(lb_binary, "-c", str(cfg), env={"LOG_LEVEL": "loud"})
    assert res.returncode == EXIT_USAGE
    assert "LOG_LEVEL" in res.stderr


def wait_for_healthz(port: int, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as resp:
                assert resp.status == 200
                assert resp.headers["Content-Type"] == "application/json"
                return json.load(resp)
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.05)


def test_serves_healthz_logs_json_and_stops_on_sigterm(lb_binary: Path, tmp_path: Path) -> None:
    port = free_port()
    cfg = write_config(tmp_path, port)
    proc = subprocess.Popen(
        [str(lb_binary), "-c", str(cfg)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "LOG_LEVEL": "info"},
    )
    try:
        body = wait_for_healthz(port)
        assert body["status"] == "ok"
        assert body["uptime_seconds"] >= 0
        proc.send_signal(signal.SIGTERM)
        _, stderr = proc.communicate(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == EXIT_OK

    records = [json.loads(line) for line in stderr.splitlines() if line.strip()]
    events = [r["event"] for r in records]
    assert events[0] == "starting"
    assert "admin_started" in events
    assert events[-1] == "stopped"
    assert all({"ts", "level", "event"} <= r.keys() for r in records)


def test_admin_port_in_use_is_a_startup_error(lb_binary: Path, tmp_path: Path) -> None:
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        cfg = write_config(tmp_path, blocker.getsockname()[1])
        res = run(lb_binary, "-c", str(cfg))
    assert res.returncode == EXIT_RUNTIME
    assert "startup_failed" in res.stderr
