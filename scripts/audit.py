#!/usr/bin/env python3
"""Chimera standalone audit — checks health, metrics, services, disk, logs, SSL."""
from __future__ import annotations

import datetime as dt
import os
import shutil
import socket
import ssl
import subprocess
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("requests not installed", file=sys.stderr)
    sys.exit(2)

BASE_URL = os.environ.get("CHIMERA_BASE_URL", "http://127.0.0.1:8080")
REPO = Path(__file__).resolve().parent.parent
SSL_HOST = os.environ.get("CHIMERA_SSL_HOST", "shovelos.com")


def _token() -> str:
    tok = os.environ.get("BRIDGE_AUTH_TOKEN", "")
    if tok:
        return tok
    env_file = REPO / "scraper.env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("BRIDGE_AUTH_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


results: list[tuple[bool, str]] = []


def ok(msg: str) -> None:
    results.append((True, msg))
    print(f"✅ {msg}")


def warn(msg: str) -> None:
    results.append((False, msg))
    print(f"⚠️  {msg}")


def fail(msg: str) -> None:
    results.append((False, msg))
    print(f"❌ {msg}")


def check_health() -> None:
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=10)
        body = r.json()
        status = body.get("status")
        uptime = body.get("uptime_seconds")
        if status == "ok":
            ok(f"/health : {status}, uptime={uptime}s")
        else:
            warn(f"/health : {status}, uptime={uptime}s")
        checks = body.get("checks", {})
        redis_c = checks.get("redis", {})
        if redis_c.get("status") == "ok":
            ok(f"Redis : latency={redis_c.get('latency_ms')}ms")
        else:
            fail("Redis : not ok")
        sqlite_c = checks.get("sqlite", {})
        m = body.get("metrics", {})
        if sqlite_c.get("status") == "ok":
            ok(f"SQLite : {sqlite_c.get('tables')} tables, {m.get('total_items_scraped')} items")
        else:
            fail("SQLite : not ok")
    except Exception as e:
        fail(f"/health unreachable: {e}")


def check_metrics() -> None:
    try:
        r = requests.get(f"{BASE_URL}/metrics", timeout=10)
        if r.status_code == 200 and "chimera_requests_total" in r.text:
            ok("Prometheus /metrics : ok")
        else:
            fail(f"/metrics : HTTP {r.status_code}")
    except Exception as e:
        fail(f"/metrics unreachable: {e}")


def check_dashboard() -> None:
    try:
        headers = {"Authorization": f"Bearer {_token()}"}
        r = requests.get(f"{BASE_URL}/dashboard", headers=headers, timeout=10)
        body = r.json()
        epids = body.get("scraping", {}).get("epids_tracked", 0)
        if epids > 0:
            ok(f"Dashboard : epids_tracked={epids}")
        else:
            warn(f"Dashboard : epids_tracked={epids} (warm-up requis)")
    except Exception as e:
        warn(f"/dashboard: {e}")


def check_services() -> None:
    for svc in ("chimera-bridge", "chimera-worker", "chimera-cron"):
        try:
            out = subprocess.run(
                ["systemctl", "is-active", svc],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
            if out == "active":
                ok(f"{svc} : active (running)")
            else:
                warn(f"{svc} : {out}")
        except Exception as e:
            warn(f"{svc} : {e}")


def check_disk() -> None:
    try:
        usage = shutil.disk_usage(str(REPO))
        pct = usage.used / usage.total * 100
        if pct > 80:
            warn(f"Disk : {pct:.0f}% used")
        else:
            ok(f"Disk : {pct:.0f}% used")
    except Exception as e:
        warn(f"Disk : {e}")


def check_logs() -> None:
    try:
        logs_dir = REPO / "logs"
        total = sum(f.stat().st_size for f in logs_dir.glob("*") if f.is_file())
        mb = total / (1024 * 1024)
        if mb > 100:
            warn(f"Logs : {mb:.0f}MB (>100MB)")
        else:
            ok(f"Logs : {mb:.0f}MB")
    except Exception as e:
        warn(f"Logs : {e}")


def check_ssl() -> None:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((SSL_HOST, 443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=SSL_HOST) as ssock:
                cert = ssock.getpeercert()
        expires = dt.datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=dt.timezone.utc
        )
        days = (expires - dt.datetime.now(dt.timezone.utc)).days
        label = f"SSL : expires {expires.date()} ({days} jours)"
        if days < 30:
            warn(label)
        else:
            ok(label)
    except Exception as e:
        warn(f"SSL : {e}")


def main() -> int:
    print(f"CHIMERA AUDIT — {dt.date.today()}")
    check_health()
    check_metrics()
    check_dashboard()
    check_services()
    check_disk()
    check_logs()
    check_ssl()
    passed = sum(1 for okk, _ in results if okk)
    total = len(results)
    print(f"RÉSULTAT : {passed}/{total} checks OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
