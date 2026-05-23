"""Tests for ProxyRotator — round-robin and host cap."""
from __future__ import annotations
import json
import time
from pathlib import Path
import pytest
from network.proxy_pool.rotator import ProxyRotator


@pytest.fixture
def pool_file(tmp_path):
    pool = {
        "tiers": {
            "residential": [
                {"url": "http://proxy-1:8000", "country": "BE", "active": True},
                {"url": "http://proxy-2:8000", "country": "FR", "active": True},
            ],
            "datacenter": [
                {"url": "http://dc-1:8000", "country": "US", "active": False},
            ],
        }
    }
    # Create network/proxy_pool subdirs and a fake storage/risk_db path
    pool_dir = tmp_path / "network" / "proxy_pool"
    pool_dir.mkdir(parents=True)
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    pool_path = pool_dir / "pool.json"
    pool_path.write_text(json.dumps(pool))
    return pool_path


@pytest.fixture
def rotator(pool_file):
    # Override DB path to use tmp_path storage
    r = ProxyRotator.__new__(ProxyRotator)
    import json as _json, sqlite3
    data = _json.loads(pool_file.read_text())
    r._proxies = [p for p in data["tiers"].get("residential", []) if p.get("active")]
    r._idx = 0
    db_path = pool_file.parent.parent.parent / "storage" / "risk_db.sqlite"
    r._db = sqlite3.connect(str(db_path))
    r._db.executescript("""
        CREATE TABLE IF NOT EXISTS proxy_use (
            proxy_url TEXT, host TEXT, ts INTEGER, status INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_proxy_use_lookup ON proxy_use(proxy_url, host, ts);
    """)
    return r


def test_round_robin_two_proxies(rotator):
    p1 = rotator.pick("example.com")
    p2 = rotator.pick("example.com")
    assert p1 is not None
    assert p2 is not None
    assert p1["url"] != p2["url"]


def test_no_active_proxies_returns_none(tmp_path):
    pool = {"tiers": {"residential": [{"url": "http://x:1", "active": False}]}}
    pool_dir = tmp_path / "network" / "proxy_pool"
    pool_dir.mkdir(parents=True)
    (tmp_path / "storage").mkdir()
    pf = pool_dir / "pool.json"
    pf.write_text(json.dumps(pool))
    r = ProxyRotator(pool_file=pf, tier="residential")
    assert r.pick("example.com") is None


def test_report_persists_to_db(rotator):
    rotator.report("http://proxy-1:8000", "example.com", 200)
    cur = rotator._db.execute(
        "SELECT proxy_url, host, status FROM proxy_use WHERE host='example.com'"
    )
    rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0][2] == 200


def test_host_cap_limits_picks(rotator):
    """After max_per_host_per_hour uses on a single proxy, it should still try the other."""
    # Fill up proxy-1 for host example.com
    for _ in range(20):
        rotator._db.execute(
            "INSERT INTO proxy_use VALUES (?, ?, ?, ?)",
            ("http://proxy-1:8000", "example.com", int(time.time()), 200)
        )
    rotator._db.commit()
    # Next pick for same host should skip proxy-1 and return proxy-2
    # (reset idx to force starting from proxy-1)
    rotator._idx = 0
    result = rotator.pick("example.com", max_per_host_per_hour=20)
    if result is not None:
        assert result["url"] == "http://proxy-2:8000"
