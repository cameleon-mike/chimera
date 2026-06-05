"""SoldDateExtractor — extract sold item data from WatchCount screenshots via Groq Vision."""
from __future__ import annotations

import base64
import logging
import re
from datetime import datetime
from pathlib import Path

from tools.groq_vision.extract_dates import parse_json_array

logger = logging.getLogger(__name__)

_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

_PROMPT = (
    "This is a screenshot of WatchCount.com showing sold eBay items.\n"
    "Extract all sold items visible with:\n"
    "- title: item title\n"
    "- end_date: date sold (ISO format YYYY-MM-DD)\n"
    "- price: sale price as float\n"
    "- watch_count: number of watchers if visible\n"
    "Return ONLY a JSON array, nothing else.\n"
    "If no items visible, return []."
)

_FR_MONTHS = {
    "janvier": "january", "février": "february", "mars": "march",
    "avril": "april", "mai": "may", "juin": "june",
    "juillet": "july", "août": "august", "septembre": "september",
    "octobre": "october", "novembre": "november", "décembre": "december",
}


class SoldDateExtractor:
    """Extracts sold item data from a WatchCount screenshot using Groq Vision."""

    def __init__(self, groq_api_key: str):
        if not groq_api_key:
            raise ValueError("groq_api_key is required for vision extraction")
        from groq import Groq
        self._client = Groq(api_key=groq_api_key)
        self._model = _MODEL

    def extract_from_screenshot(self, png_path: str) -> list[dict]:
        """Read PNG bytes from file and delegate to extract_from_png_bytes.

        Returns [] if file not found.
        """
        try:
            p = Path(png_path)
            if not p.exists():
                return []
            return self.extract_from_png_bytes(p.read_bytes())
        except Exception as exc:
            logger.warning("sold_date_extractor_file_error: %s", repr(exc))
            return []

    def extract_from_png_bytes(self, png_bytes: bytes) -> list[dict]:
        """Send PNG bytes to Groq Vision and extract sold item data.

        Returns [] on any error (Groq down, JSON invalid, etc.).
        """
        try:
            b64 = base64.b64encode(png_bytes).decode()
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                        {"type": "text", "text": _PROMPT},
                    ],
                }],
                max_tokens=2048,
                temperature=0.0,
            )
            raw = (response.choices[0].message.content or "").strip()
            items = parse_json_array(raw)
            result = []
            for item in items:
                parsed_date = self._parse_date(item.get("end_date", ""))
                if parsed_date is None:
                    continue
                item["end_date"] = parsed_date
                result.append(item)
            return result
        except Exception as exc:
            logger.warning("sold_date_extractor_error: %s", repr(exc))
            return []

    def _parse_date(self, raw: str) -> str | None:
        """Parse various date formats to ISO YYYY-MM-DD.

        - "May 15, 2026" -> "2026-05-15"
        - "15 mai 2026" -> "2026-05-15"  (French months)
        - "Sold May 15" -> "<current_year>-05-15"
        - Already ISO "2026-05-15" -> return as-is
        - Non-parseable -> None
        """
        if not raw:
            return None

        raw = str(raw).strip()

        # Already ISO
        if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
            return raw

        # Translate French months to English
        lower = raw.lower()
        for fr, en in _FR_MONTHS.items():
            if fr in lower:
                lower = lower.replace(fr, en)
                raw = lower
                break

        # Strip "Sold " prefix
        has_sold_prefix = False
        cleaned = raw.strip()
        if re.match(r"^sold\s+", cleaned, re.IGNORECASE):
            cleaned = re.sub(r"^sold\s+", "", cleaned, flags=re.IGNORECASE).strip()
            has_sold_prefix = True

        # Try formats with year first
        for fmt in ("%B %d, %Y", "%d %B %Y", "%B %d %Y", "%b %d, %Y", "%d %b %Y", "%b %d %Y"):
            try:
                dt = datetime.strptime(cleaned, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

        # Try formats without year (use current year)
        for fmt in ("%B %d", "%b %d", "%d %B", "%d %b"):
            try:
                dt = datetime.strptime(cleaned, fmt)
                year = datetime.now().year
                return f"{year}-{dt.strftime('%m-%d')}"
            except ValueError:
                continue

        # If had sold prefix, try with year appended
        if has_sold_prefix:
            year = datetime.now().year
            with_year = f"{cleaned} {year}"
            for fmt in ("%B %d %Y", "%b %d %Y"):
                try:
                    dt = datetime.strptime(with_year, fmt)
                    return dt.strftime("%Y-%m-%d")
                except ValueError:
                    continue

        return None
