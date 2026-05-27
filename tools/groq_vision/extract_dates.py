"""Groq Vision — extract WatchCount listing data from a screenshot PNG.

Used as the fallback when watchcount.com shows reCAPTCHA to Scrapy.
The extractor sends the PNG (base64) to Groq's vision model and parses
structured item data (title, watch_count, end_date, price, ebay_url).
"""
from __future__ import annotations

import base64
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

_PROMPT = (
    "You are analyzing a screenshot of WatchCount.com search results for \"{query}\".\n"
    "Today's date (UTC) is {today}.\n\n"
    "Extract ALL visible listings from the page. For each listing return a JSON object with:\n"
    "- title: the item title (string)\n"
    "- watch_count: number of watchers shown (integer or null)\n"
    '- end_date: auction end date in YYYY-MM-DD format — compute from "time remaining" using today as reference. null if unavailable.\n'
    "- price: numeric price value as float (currency stripped, or null)\n"
    "- ebay_url: the eBay item URL if visible (string or null)\n"
    "- ebay_item_id: eBay item ID extracted from the URL (12+ digit string, or null)\n\n"
    "Return ONLY a valid JSON array — no markdown fences, no explanation.\n"
    'Example: [{{"title": "Wacom Cintiq 16", "watch_count": 458, "end_date": "2026-06-01", '
    '"price": 349.99, "ebay_url": "https://www.ebay.fr/itm/123456789012", "ebay_item_id": "123456789012"}}]\n\n'
    "If no listings are visible (e.g. CAPTCHA page), return: []"
)


class GroqVisionExtractor:
    """Extracts listing data from a WatchCount screenshot using Groq Vision."""

    def __init__(self, api_key: str, model: str = _MODEL):
        if not api_key:
            raise ValueError("GROQ_API_KEY is required for vision extraction")
        from groq import Groq
        self._client = Groq(api_key=api_key)
        self._model = model

    def extract_items(self, image_source: str | Path, query: str = "") -> list[dict]:
        """Extract listing items from a PNG screenshot.

        image_source: path to an existing PNG file or a base64-encoded PNG string.
        Returns a (possibly empty) list of item dicts.
        """
        b64 = _to_base64(image_source)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        prompt_text = _PROMPT.format(query=query, today=today)

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{b64}"},
                            },
                            {"type": "text", "text": prompt_text},
                        ],
                    }
                ],
                max_tokens=2048,
                temperature=0.0,
            )
        except Exception as exc:
            logger.error("groq_vision_api_error: %s", repr(exc))
            return []

        raw = (response.choices[0].message.content or "").strip()
        return parse_json_array(raw)


# ---------------------------------------------------------------------------
# Helpers (module-level so tests can import them directly)
# ---------------------------------------------------------------------------


def _to_base64(source: str | Path) -> str:
    """Return base64-encoded PNG from a file path or an already-encoded string."""
    p = Path(str(source))
    if p.exists():
        return base64.b64encode(p.read_bytes()).decode()
    return str(source)


def parse_json_array(text: str) -> list[dict]:
    """Extract a JSON array from potentially noisy LLM output."""
    text = text.strip()
    # Strip markdown fences
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if m:
        text = m.group(1).strip()
    # Find first '[' … last ']'
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        logger.warning("groq_vision_no_json_array in: %.200s", text)
        return []
    try:
        data = json.loads(text[start : end + 1])
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []
    except json.JSONDecodeError as exc:
        logger.warning("groq_vision_json_parse_error: %s | raw: %.200s", exc, text)
        return []
