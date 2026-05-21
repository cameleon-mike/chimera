"""Tests for the Scrapy runner CLI (`tools.scrapy_runner.run_scrapy`).

Covers input validation, settings build, result persistence, and the full
JSON-in / JSON-out CLI contract documented in run_scrapy.py.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path

import pytest

from tools.scrapy_runner import run_scrapy


# ---------- _read_input -------------------------------------------------

def test_read_input_from_file(tmp_path: Path):
    payload = {"url": "https://httpbin.org/get", "config": {"spider": "api_json"}}
    f = tmp_path / "in.json"
    f.write_text(json.dumps(payload), encoding="utf-8")
    got = run_scrapy._read_input(["--input-file", str(f)])
    assert got == payload


def test_read_input_invalid_json_exits_2(tmp_path: Path, capsys):
    f = tmp_path / "broken.json"
    f.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        run_scrapy._read_input(["--input-file", str(f)])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert json.loads(err)["error"] == "invalid_json"


# ---------- _validate ---------------------------------------------------

def test_validate_single_url_string():
    urls, spider, config, job_id = run_scrapy._validate(
        {"url": "https://example.com", "config": {"spider": "api_json"}, "job_id": "abc123"}
    )
    assert urls == ["https://example.com"]
    assert spider == "api_json"
    assert job_id == "abc123"


def test_validate_url_list():
    urls, spider, _, _ = run_scrapy._validate(
        {"url": ["https://a.test", "https://b.test"], "config": {"spider": "adaptive"}}
    )
    assert urls == ["https://a.test", "https://b.test"]
    assert spider == "adaptive"


def test_validate_default_spider_is_api_json():
    _, spider, _, _ = run_scrapy._validate({"url": "https://x.test"})
    assert spider == "api_json"


def test_validate_generates_job_id_when_missing():
    _, _, _, job_id = run_scrapy._validate({"url": "https://x.test"})
    assert isinstance(job_id, str) and len(job_id) == 16  # token_hex(8) → 16 chars


def test_validate_missing_url_exits_2(capsys):
    with pytest.raises(SystemExit) as exc:
        run_scrapy._validate({"config": {}})
    assert exc.value.code == 2
    assert json.loads(capsys.readouterr().err)["error"] == "url_required"


def test_validate_empty_url_list_exits_2(capsys):
    with pytest.raises(SystemExit) as exc:
        run_scrapy._validate({"url": []})
    assert exc.value.code == 2


def test_validate_unknown_spider_exits_2(capsys):
    with pytest.raises(SystemExit) as exc:
        run_scrapy._validate({"url": "https://x.test", "config": {"spider": "ghost"}})
    assert exc.value.code == 2
    err = json.loads(capsys.readouterr().err)
    assert err["error"] == "unknown_spider"
    assert "api_json" in err["available"] and "adaptive" in err["available"]


def test_validate_rejects_path_traversal_job_id(capsys):
    with pytest.raises(SystemExit) as exc:
        run_scrapy._validate({"url": "https://x.test", "job_id": "../../../etc/passwd"})
    assert exc.value.code == 2
    err = json.loads(capsys.readouterr().err)
    assert err["error"] == "invalid_job_id"


# ---------- _build_settings --------------------------------------------

def test_build_settings_respect_robots_override():
    s = run_scrapy._build_settings({"respect_robots": False})
    assert s.getbool("ROBOTSTXT_OBEY") is False


def test_build_settings_passthrough():
    s = run_scrapy._build_settings({"settings": {"DOWNLOAD_DELAY": 2.5}})
    assert s.getfloat("DOWNLOAD_DELAY") == 2.5


def test_build_settings_defaults_preserved():
    s = run_scrapy._build_settings({})
    # Default from project/settings.py
    assert s.getbool("ROBOTSTXT_OBEY") is True
    assert s.getfloat("DOWNLOAD_DELAY") == 1.0


# ---------- _persist_result --------------------------------------------

def test_persist_result_atomic_write(isolated_settings, tmp_path: Path):
    job_id = secrets.token_hex(4)
    payload = {"tool": "scrapy", "items": [{"x": 1}]}
    out = run_scrapy._persist_result(job_id, payload)
    assert out.exists()
    assert out.name == f"{job_id}.json"
    assert out.parent == isolated_settings.results_dir
    # tmp file should be gone (replaced atomically)
    assert not out.with_suffix(".json.tmp").exists()
    on_disk = json.loads(out.read_text(encoding="utf-8"))
    assert on_disk == payload


# ---------- _iso_now ---------------------------------------------------

def test_iso_now_format():
    ts = run_scrapy._iso_now()
    # YYYY-MM-DDTHH:MM:SS.ffffffZ
    assert ts.endswith("Z")
    assert "T" in ts
    assert len(ts) == 27  # 4+1+2+1+2+1+2+1+2+1+2+1+6+1


# ---------- _SPIDERS registry ------------------------------------------

def test_spiders_registry_contains_both():
    assert set(run_scrapy._SPIDERS) == {"api_json", "adaptive"}
