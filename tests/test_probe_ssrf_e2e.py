"""Integration tests: SSRF guard on /probe and /risk endpoints."""
import pytest
from fastapi.testclient import TestClient

from bridge.app import app
from bridge.auth import require_bearer

# Bypass auth so FQDN validation is reached before token check
app.dependency_overrides[require_bearer] = lambda: "test-token"

client = TestClient(app)

SSRF_DOMAINS = [
    "169.254.169.254",
    "localhost",
    "10.0.0.1",
    "127.0.0.1",
    "intranet",
]

HEADERS = {"Authorization": "Bearer test-token"}


@pytest.mark.parametrize("domain", SSRF_DOMAINS)
def test_probe_rejects_ssrf(domain):
    resp = client.get(f"/probe/{domain}", headers=HEADERS)
    assert resp.status_code == 422, f"/probe/{domain} returned {resp.status_code}"


@pytest.mark.parametrize("domain", SSRF_DOMAINS)
def test_risk_rejects_ssrf(domain):
    resp = client.get(f"/risk/{domain}", headers=HEADERS)
    assert resp.status_code == 422, f"/risk/{domain} returned {resp.status_code}"
