"""Test hard-cap 15s in probe_domain() — TD-13."""
from __future__ import annotations

import time
import urllib.request
from unittest.mock import patch

import pytest


def test_probe_timeout_hard_cap(monkeypatch):
    """Simulate a hanging urlopen — probe_domain must return within 16s with timeout=True."""
    original_urlopen = urllib.request.urlopen

    def hanging_urlopen(*args, **kwargs):
        time.sleep(20)  # exceeds the 15s hard cap
        return original_urlopen(*args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", hanging_urlopen)

    # Import after monkeypatching so the patched urlopen is used inside _inner()
    from tools.probe.security_probe import probe_domain

    t0 = time.perf_counter()
    result = probe_domain("example.com")
    elapsed = time.perf_counter() - t0

    assert elapsed < 16.0, f"Probe took {elapsed:.1f}s — hard-cap not enforced"
    assert result.get("timeout") is True
    assert result.get("risk_score") is None


def test_probe_normal_result_has_timeout_false(monkeypatch):
    """When probe succeeds quickly, timeout key must be False."""
    import urllib.error

    class _FakeResponse:
        status = 200
        headers = {}

        def read(self, n=None):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fast_urlopen(*args, **kwargs):
        return _FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fast_urlopen)

    from tools.probe.security_probe import probe_domain

    result = probe_domain("example.com")
    # Either a real result with timeout=False or the _zero_result (which also has timeout=False)
    assert result.get("timeout") is False
