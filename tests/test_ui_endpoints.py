"""Tests for /ui static file serving endpoints."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bridge.app import app

client = TestClient(app)


def test_ui_root_200():
    r = client.get("/ui")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_ui_trailing_slash_200():
    r = client.get("/ui/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_ui_contains_chimera():
    r = client.get("/ui")
    assert r.status_code == 200
    assert "CHIMERA" in r.text


def test_ui_static_style_css():
    css_path = Path(__file__).parent.parent / "bridge" / "ui" / "static" / "style.css"
    if not css_path.exists():
        pytest.skip("style.css not present")
    r = client.get("/ui/static/style.css")
    assert r.status_code == 200
