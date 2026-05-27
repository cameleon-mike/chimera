"""Tests for tools/stats/epid_calculator.py — 15 tests."""

from __future__ import annotations

import sqlite3
import pytest
from tools.stats.epid_calculator import (
    compute_price_stats,
    compute_sell_days,
    upsert_epid_stats,
    recompute_all_stats,
)


# --- compute_price_stats ---

def test_price_stats_single():
    r = compute_price_stats([100.0])
    assert r["median"] == 100.0
    assert r["q4"] == 100.0

def test_price_stats_empty():
    r = compute_price_stats([])
    assert r["median"] is None
    assert r["q1"] is None

def test_price_stats_two_values():
    r = compute_price_stats([100.0, 200.0])
    assert r["median"] == 150.0

def test_price_stats_five_values():
    r = compute_price_stats([10.0, 20.0, 30.0, 40.0, 50.0])
    assert r["median"] == 30.0
    assert r["q1"] == 15.0
    assert r["q3"] == 45.0
    assert r["q4"] == 50.0

def test_price_stats_q2_equals_median():
    r = compute_price_stats([1.0, 2.0, 3.0])
    assert r["q2"] == r["median"]


# --- compute_sell_days ---

def test_sell_days_basic():
    items = [
        {"start_date": "2026-01-01T00:00:00Z", "end_date": "2026-01-11T00:00:00Z"},
        {"start_date": "2026-01-01T00:00:00Z", "end_date": "2026-01-06T00:00:00Z"},
    ]
    r = compute_sell_days(items)
    assert r["avg_sell_days"] == 7.5
    assert r["min_sell_days"] == 5.0
    assert r["max_sell_days"] == 10.0
    assert r["sell_days_sample"] == 2

def test_sell_days_none_ignored():
    items = [
        {"start_date": None, "end_date": "2026-01-11T00:00:00Z"},
        {"start_date": "2026-01-01T00:00:00Z", "end_date": None},
        {"start_date": "2026-01-01T00:00:00Z", "end_date": "2026-01-06T00:00:00Z"},
    ]
    r = compute_sell_days(items)
    assert r["sell_days_sample"] == 1
    assert r["avg_sell_days"] == 5.0

def test_sell_days_negative_ignored():
    items = [
        {"start_date": "2026-01-10T00:00:00Z", "end_date": "2026-01-05T00:00:00Z"},
        {"start_date": "2026-01-01T00:00:00Z", "end_date": "2026-01-06T00:00:00Z"},
    ]
    r = compute_sell_days(items)
    assert r["sell_days_sample"] == 1
    assert r["avg_sell_days"] == 5.0

def test_sell_days_all_none():
    items = [{"start_date": None, "end_date": None}]
    r = compute_sell_days(items)
    assert r["avg_sell_days"] is None
    assert r["sell_days_sample"] == 0

def test_sell_days_empty():
    r = compute_sell_days([])
    assert r["avg_sell_days"] is None
    assert r["sell_days_sample"] == 0


# --- upsert_epid_stats ---

@pytest.fixture
def mem_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE epid_stats (
            epid TEXT PRIMARY KEY, brand TEXT, model TEXT,
            total_items INTEGER DEFAULT 0, currency TEXT,
            median_price REAL, q1_price REAL, q2_price REAL,
            q3_price REAL, q4_price REAL,
            avg_sell_days REAL, min_sell_days REAL, max_sell_days REAL,
            sell_days_sample INTEGER DEFAULT 0, last_updated TEXT
        );
        CREATE TABLE scraped_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, epid TEXT,
            title TEXT, price_value REAL, price_currency TEXT,
            start_date TEXT, end_date TEXT, source TEXT,
            url TEXT UNIQUE, scraped_at TEXT
        );
    """)
    yield conn
    conn.close()

def test_upsert_inserts(mem_db):
    items = [
        {"title": "Wacom Cintiq 16", "price_value": 250.0,
         "price_currency": "EUR", "start_date": None, "end_date": None},
    ]
    upsert_epid_stats(mem_db, "EP001", items)
    row = mem_db.execute("SELECT epid, brand, total_items FROM epid_stats WHERE epid='EP001'").fetchone()
    assert row is not None
    assert row[1] == "Wacom"
    assert row[2] == 1

def test_upsert_replaces_on_rerun(mem_db):
    items1 = [{"title": "Wacom Cintiq 16", "price_value": 200.0, "price_currency": "EUR",
                "start_date": None, "end_date": None}]
    upsert_epid_stats(mem_db, "EP001", items1)
    items2 = [
        {"title": "Wacom Cintiq 16", "price_value": 200.0, "price_currency": "EUR",
         "start_date": None, "end_date": None},
        {"title": "Wacom Cintiq 16", "price_value": 300.0, "price_currency": "EUR",
         "start_date": None, "end_date": None},
    ]
    upsert_epid_stats(mem_db, "EP001", items2)
    row = mem_db.execute("SELECT total_items, median_price FROM epid_stats WHERE epid='EP001'").fetchone()
    assert row[0] == 2
    assert row[1] == 250.0


# --- recompute_all_stats ---

def test_recompute_all_stats(mem_db):
    mem_db.execute("""
        INSERT INTO scraped_items (epid, title, price_value, price_currency, url, scraped_at)
        VALUES ('EP001', 'Wacom Cintiq 16', 250.0, 'EUR', 'http://a.com', '2026-01-01'),
               ('EP001', 'Wacom Cintiq 16', 350.0, 'EUR', 'http://b.com', '2026-01-01'),
               ('EP002', 'Apple iPad Pro', 800.0, 'EUR', 'http://c.com', '2026-01-01')
    """)
    mem_db.commit()
    epids = recompute_all_stats(mem_db)
    assert set(epids) == {"EP001", "EP002"}
    row1 = mem_db.execute("SELECT total_items FROM epid_stats WHERE epid='EP001'").fetchone()
    assert row1[0] == 2
    row2 = mem_db.execute("SELECT total_items FROM epid_stats WHERE epid='EP002'").fetchone()
    assert row2[0] == 1

def test_recompute_empty_db(mem_db):
    epids = recompute_all_stats(mem_db)
    assert epids == []
