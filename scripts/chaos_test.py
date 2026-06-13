#!/usr/bin/env python3
"""Standalone chaos test script for live bridge HTTP testing.

Fires against a running bridge instance and validates resilience.
No real systemd kills or network simulation — just HTTP stress tests.
"""

import os
import sys
import time
import threading
from typing import Tuple
import requests

from bridge.config import get_settings

BASE = os.environ.get("BRIDGE_URL", "http://127.0.0.1:8080")
TOKEN = os.environ.get("TOKEN") or get_settings().bridge_auth_token
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def test_invalid_requests() -> Tuple[bool, str]:
    """Verify invalid request patterns return 422 or 404."""
    failures = []

    try:
        # GET /ebay/search WITH AUTH, no q param -> 422
        r = requests.get(f"{BASE}/ebay/search", headers=AUTH, timeout=10)
        if r.status_code != 422:
            failures.append(f"/ebay/search (no q): got {r.status_code} want 422")
    except Exception as e:
        failures.append(f"/ebay/search (no q): {e}")

    try:
        # POST /run-tool WITH AUTH, invalid tool -> 422
        r = requests.post(
            f"{BASE}/run-tool",
            headers=AUTH,
            json={"tool": "definitely_not_a_tool", "url": "http://example.com"},
            timeout=10,
        )
        if r.status_code != 422:
            failures.append(f"/run-tool (bad tool): got {r.status_code} want 422")
    except Exception as e:
        failures.append(f"/run-tool (bad tool): {e}")

    try:
        # GET /epid/stats/FAKE_EPID -> 404
        r = requests.get(f"{BASE}/epid/stats/FAKE_EPID_XYZ", headers=AUTH, timeout=10)
        if r.status_code != 404:
            failures.append(f"/epid/stats/FAKE: got {r.status_code} want 404")
    except Exception as e:
        failures.append(f"/epid/stats/FAKE: {e}")

    try:
        # GET /nonexistent (no auth) -> 404
        r = requests.get(f"{BASE}/this_path_does_not_exist_xyz", timeout=10)
        if r.status_code != 404:
            failures.append(f"/nonexistent: got {r.status_code} want 404")
    except Exception as e:
        failures.append(f"/nonexistent: {e}")

    try:
        # GET /stealth/runs/FAKE -> 404
        r = requests.get(f"{BASE}/stealth/runs/FAKE_ID_XYZ", headers=AUTH, timeout=10)
        if r.status_code != 404:
            failures.append(f"/stealth/runs/FAKE: got {r.status_code} want 404")
    except Exception as e:
        failures.append(f"/stealth/runs/FAKE: {e}")

    try:
        # POST /stealth/run WITH AUTH, empty body -> 422
        r = requests.post(f"{BASE}/stealth/run", headers=AUTH, json={}, timeout=10)
        if r.status_code != 422:
            failures.append(f"/stealth/run (empty): got {r.status_code} want 422")
    except Exception as e:
        failures.append(f"/stealth/run (empty): {e}")

    ok = len(failures) == 0
    detail = "; ".join(failures) if failures else "all 422/404 checks passed"
    return ok, detail


def test_high_load() -> Tuple[bool, str]:
    """Fire 10 concurrent GET requests to /health."""
    results = []

    def worker():
        try:
            start = time.time()
            r = requests.get(f"{BASE}/health", timeout=10)
            elapsed = time.time() - start
            results.append((r.status_code, elapsed))
        except Exception as e:
            results.append((None, None))

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ok = (
        len(results) == 10
        and all(r[0] == 200 for r in results if r[0] is not None)
        and all(r[1] < 2.0 for r in results if r[1] is not None)
    )
    max_elapsed = max((r[1] for r in results if r[1] is not None), default=0)
    success_count = sum(1 for r in results if r[0] == 200)
    detail = f"{success_count}/10 200, max={max_elapsed:.2f}s"
    return ok, detail


def test_scraper_timeout() -> Tuple[bool, str]:
    """POST /run-tool with unroutable URL (should enqueue fast, not 500)."""
    try:
        start = time.time()
        r = requests.post(
            f"{BASE}/run-tool",
            headers=AUTH,
            json={"tool": "crawl4ai", "url": "http://192.0.2.1"},
            timeout=120,
        )
        elapsed = time.time() - start

        is_valid = r.status_code < 500
        is_structured = False
        try:
            body = r.json()
            is_structured = isinstance(body, dict)
        except Exception:
            pass

        ok = r.status_code != 500 and is_valid and is_structured and elapsed < 120
        detail = f"status={r.status_code} elapsed={elapsed:.2f}s structured={is_structured}"
        return ok, detail
    except Exception as e:
        return False, str(e)


def test_stealth_resilience() -> Tuple[bool, str]:
    """POST /stealth/run with invalid domain, verify error persists."""
    try:
        start = time.time()
        r = requests.post(
            f"{BASE}/stealth/run",
            headers=AUTH,
            json={
                "url": "http://nonexistent.invalid.chimera-chaos.tld",
                "source": "chaos",
                "query": "chaos",
            },
            timeout=120,
        )
        elapsed = time.time() - start

        if r.status_code == 504:
            return False, f"timeout after {elapsed:.2f}s"

        if r.status_code != 200:
            return False, f"status={r.status_code}"

        body = r.json()
        run_id = body.get("run_id")
        status = body.get("status")

        if not run_id or status != "error":
            return False, f"run_id={run_id} status={status}"

        # Verify row persisted
        time.sleep(0.5)
        r2 = requests.get(f"{BASE}/stealth/runs/{run_id}", headers=AUTH, timeout=10)
        persisted = False
        if r2.status_code == 200:
            body2 = r2.json()
            persisted = body2.get("status") == "error"

        ok = run_id is not None and status == "error" and persisted
        detail = f"run_id={run_id} status={status} persisted={persisted}"
        return ok, detail
    except Exception as e:
        return False, str(e)


def test_endpoints_auth() -> Tuple[bool, str]:
    """Verify protected endpoints require auth; public ones don't."""
    failures = []

    # Protected endpoints WITHOUT auth -> expect 401
    protected = [
        ("GET", f"{BASE}/ebay/search?q=x"),
        ("POST", f"{BASE}/run-tool", {"tool": "crawl4ai", "url": "http://x"}),
        ("GET", f"{BASE}/epid/stats/x"),
        ("GET", f"{BASE}/stealth/runs"),
        ("POST", f"{BASE}/stealth/run", {"url": "http://x"}),
    ]

    for method, url, *payload in protected:
        try:
            if method == "GET":
                r = requests.get(url, timeout=10)
            else:
                r = requests.post(url, json=payload[0] if payload else {}, timeout=10)
            if r.status_code != 401:
                failures.append(f"{method} {url}: got {r.status_code} want 401")
        except Exception as e:
            failures.append(f"{method} {url}: {e}")

    # Public endpoints WITHOUT auth -> expect 200
    public = [
        ("GET", f"{BASE}/health"),
        ("GET", f"{BASE}/metrics"),
        ("GET", f"{BASE}/ui"),
    ]

    for method, url in public:
        try:
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                failures.append(f"{method} {url}: got {r.status_code} want 200")
        except Exception as e:
            failures.append(f"{method} {url}: {e}")

    ok = len(failures) == 0
    detail = "; ".join(failures) if failures else "all auth checks passed"
    return ok, detail


def main():
    """Run all tests and report."""
    tests = [
        ("Invalid requests", test_invalid_requests),
        ("High load", test_high_load),
        ("Scraper timeout", test_scraper_timeout),
        ("Stealth resilience", test_stealth_resilience),
        ("Auth", test_endpoints_auth),
    ]

    date_str = time.strftime("%Y-%m-%d")
    print(f"CHAOS TEST — {date_str}")

    results = []
    for name, test_func in tests:
        ok, detail = test_func()
        emoji = "✅" if ok else "❌"
        print(f"{emoji} {name} : {detail}")
        results.append(ok)

    passed = sum(results)
    total = len(results)
    print(f"RÉSULTAT : {passed}/{total} tests OK")

    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
