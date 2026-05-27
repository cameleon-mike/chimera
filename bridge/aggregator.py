"""Multi-source aggregator: parallel eBay + 2ememain fetch + fuzzy deduplication."""
from __future__ import annotations

import asyncio
import re
import uuid
from difflib import SequenceMatcher
from typing import Any


def _normalize(title: str | None) -> str:
    if not title:
        return ""
    t = title.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _similar_titles(a: str | None, b: str | None, threshold: float = 0.82) -> bool:
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return False
    return SequenceMatcher(None, na, nb).ratio() >= threshold


def _price_val(price: Any) -> float | None:
    if price is None:
        return None
    if hasattr(price, "value"):
        return price.value
    if isinstance(price, dict):
        return price.get("value")
    return None


def _prices_close(pa: float | None, pb: float | None, tol: float = 0.25) -> bool:
    if pa is None or pb is None:
        return True  # can't compare — keep the item
    if max(pa, pb) == 0:
        return True
    return abs(pa - pb) / max(pa, pb) <= tol


def deduplicate(ebay_items: list, twoememain_items: list) -> tuple[list, int]:
    """Merge eBay + 2ememain items; remove 2ememain near-duplicates of eBay entries.

    Returns (merged_list, n_duplicates_removed).
    Criteria: title similarity ≥ 0.82 AND price within 25%.
    """
    from .schemas import AggregatedItem

    merged: list[AggregatedItem] = []
    n_dups = 0

    for item in ebay_items:
        merged.append(AggregatedItem(
            title=item.title,
            price=item.price,
            epid=item.epid,
            start_date=item.start_date,
            end_date=item.end_date,
            photo_url=item.photo_url,
            link=item.link,
            source="ebay",
        ))

    for item in twoememain_items:
        pv = _price_val(item.price)
        is_dup = any(
            _similar_titles(item.title, e.title) and _prices_close(pv, _price_val(e.price))
            for e in merged
            if e.source == "ebay"
        )
        if is_dup:
            n_dups += 1
        else:
            merged.append(AggregatedItem(
                title=item.title,
                price=item.price,
                start_date=item.start_date,
                end_date=item.end_date,
                photo_url=item.photo_url,
                link=item.link,
                location=item.location,
                source="2ememain",
            ))

    return merged, n_dups


async def fetch_ebay_raw(q: str, marketplace: str, max_pages: int, settings: Any) -> dict:
    """Run eBay Browse spider; return raw result dict. Swallows errors → empty items."""
    from .workers import _run_scrapy_subprocess

    job_id = uuid.uuid4().hex[:16]
    config = {
        "spider": "ebay_browse",
        "q": q,
        "marketplace_id": marketplace,
        "max_pages": max_pages,
        "respect_robots": False,
        "ebay_app_ids": getattr(settings, "ebay_app_ids", []),
        "ebay_cert_ids": getattr(settings, "ebay_cert_ids", []),
    }
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                _run_scrapy_subprocess,
                job_id,
                "https://api.ebay.com/buy/browse/v1/item_summary/search",
                config,
            ),
            timeout=120.0,
        )
    except (asyncio.TimeoutError, Exception):
        return {"items": [], "_meta": {"error": "fetch_failed"}}


async def fetch_2ememain_raw(q: str, max_pages: int) -> dict:
    """Run 2ememain spider; return raw result dict. Swallows errors → empty items."""
    from .workers import _run_scrapy_subprocess

    job_id = uuid.uuid4().hex[:16]
    config = {
        "spider": "2ememain",
        "q": q,
        "max_pages": max_pages,
        "respect_robots": False,
    }
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                _run_scrapy_subprocess,
                job_id,
                f"https://www.2ememain.be/q/{q}/",
                config,
            ),
            timeout=120.0,
        )
    except (asyncio.TimeoutError, Exception):
        return {"items": [], "_meta": {"blocked": False, "error": "fetch_failed"}}
