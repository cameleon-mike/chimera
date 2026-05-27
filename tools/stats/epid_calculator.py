"""Pure-function ePID statistics calculator."""

from __future__ import annotations

import sqlite3
import statistics
from datetime import datetime, timezone


def compute_price_stats(prices: list[float]) -> dict:
    """Compute median and quartiles from a list of prices."""
    if not prices:
        return {
            "median": None, "q1": None, "q2": None, "q3": None, "q4": None
        }
    sorted_p = sorted(prices)
    n = len(sorted_p)
    median = statistics.median(sorted_p)
    mid = n // 2
    lower = sorted_p[:mid]
    upper = sorted_p[mid:] if n % 2 == 0 else sorted_p[mid + 1:]
    q1 = statistics.median(lower) if lower else sorted_p[0]
    q3 = statistics.median(upper) if upper else sorted_p[-1]
    return {
        "median": median,
        "q1": q1,
        "q2": median,  # q2 == median
        "q3": q3,
        "q4": max(sorted_p),
    }


def compute_sell_days(items: list[dict]) -> dict:
    """Compute sell-time stats from items with start_date and end_date."""
    sell_days = []
    for item in items:
        start = item.get("start_date")
        end = item.get("end_date")
        if not start or not end:
            continue
        try:
            # Parse ISO 8601, strip timezone suffix for fromisoformat compat
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
            days = (end_dt - start_dt).days
            if days < 0:
                continue
            sell_days.append(days)
        except (ValueError, AttributeError):
            continue

    if not sell_days:
        return {
            "avg_sell_days": None,
            "min_sell_days": None,
            "max_sell_days": None,
            "sell_days_sample": 0,
        }
    return {
        "avg_sell_days": round(sum(sell_days) / len(sell_days), 2),
        "min_sell_days": float(min(sell_days)),
        "max_sell_days": float(max(sell_days)),
        "sell_days_sample": len(sell_days),
    }


def _extract_brand_model(title: str | None) -> tuple[str | None, str | None]:
    """Naive brand/model extraction: first word = brand, next 2 = model."""
    if not title:
        return None, None
    parts = title.strip().split()
    brand = parts[0] if parts else None
    model = " ".join(parts[1:3]) if len(parts) > 1 else None
    return brand, model


def upsert_epid_stats(conn: sqlite3.Connection, epid: str, items: list[dict]) -> None:
    """Compute and upsert stats for one ePID."""
    prices = [
        item["price_value"]
        for item in items
        if item.get("price_value") is not None
    ]
    price_stats = compute_price_stats(prices)
    sell_stats = compute_sell_days(items)

    first_item = items[0] if items else {}
    brand, model = _extract_brand_model(first_item.get("title"))
    currency = first_item.get("price_currency")
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """
        INSERT OR REPLACE INTO epid_stats
            (epid, brand, model, total_items, currency,
             median_price, q1_price, q2_price, q3_price, q4_price,
             avg_sell_days, min_sell_days, max_sell_days, sell_days_sample,
             last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            epid, brand, model, len(items), currency,
            price_stats["median"], price_stats["q1"], price_stats["q2"],
            price_stats["q3"], price_stats["q4"],
            sell_stats["avg_sell_days"], sell_stats["min_sell_days"],
            sell_stats["max_sell_days"], sell_stats["sell_days_sample"],
            now,
        ),
    )
    conn.commit()


def recompute_all_stats(conn: sqlite3.Connection) -> list[str]:
    """Recompute stats for all distinct ePIDs in scraped_items."""
    cur = conn.execute("SELECT DISTINCT epid FROM scraped_items WHERE epid IS NOT NULL")
    epids = [row[0] for row in cur.fetchall()]

    for epid in epids:
        cur2 = conn.execute(
            """
            SELECT title, price_value, price_currency, start_date, end_date, source, url
            FROM scraped_items WHERE epid = ?
            """,
            (epid,),
        )
        items = [
            {
                "title": r[0], "price_value": r[1], "price_currency": r[2],
                "start_date": r[3], "end_date": r[4], "source": r[5], "url": r[6],
            }
            for r in cur2.fetchall()
        ]
        upsert_epid_stats(conn, epid, items)

    return epids
