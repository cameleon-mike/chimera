"""Universal Extractor — CSS-first, LLM fallback extraction engine."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import structlog
from bs4 import BeautifulSoup

# Import Groq at module level so tests can patch it via
# patch("tools.extractors.universal_extractor.Groq")
try:
    from groq import Groq
except ImportError:
    Groq = None  # type: ignore

logger = structlog.get_logger()

REPO_ROOT = Path(__file__).resolve().parents[2]

_COND_MAP = {
    "neuf avec étiquette": "new_with_tags",
    "très bon état": "very_good",
    "bon état": "good",
    "satisfaisant": "satisfactory",
}


class UniversalExtractor:
    def __init__(self, schema_path: str, groq_api_key: str = ""):
        self.schema_path = Path(schema_path)
        self.groq_api_key = groq_api_key
        with open(self.schema_path, encoding="utf-8") as f:
            self.schema = json.load(f)

    def extract(self, html: str, markdown: str = None) -> list[dict]:
        """Cascade CSS → LLM. Returns validated items."""
        items = self._css_extract(html)
        if not items:
            llm_items = self._llm_extract(markdown or "")
            if llm_items:
                self._repair_schema(html, llm_items)
            items = llm_items
        return [i for i in items if self._validate(i)]

    def _css_extract(self, html: str) -> list[dict]:
        """Extract items using BeautifulSoup + JSON schema selectors."""
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(self.schema["baseSelector"])
        results = []
        for card in cards:
            raw: dict[str, Any] = {}
            for field in self.schema["fields"]:
                name = field["name"]
                selector = field["selector"]
                ftype = field["type"]
                transform = field.get("transform")
                attribute = field.get("attribute")
                try:
                    el = card.select_one(selector)
                    if el is None:
                        raw[name] = None
                        continue
                    if ftype == "text":
                        raw[name] = el.get_text(strip=True)
                    elif ftype == "attribute":
                        raw[name] = el.get(attribute)
                    else:
                        raw[name] = None

                    if transform == "extract_id_from_url" and raw[name]:
                        m = re.search(r"/(\d+)", raw[name])
                        raw[name] = m.group(1) if m else None
                except Exception:
                    raw[name] = None
            results.append(self._build_item(raw))
        return results

    def _llm_extract(self, markdown: str) -> list[dict]:
        """LLM fallback extraction via Groq. Always returns [] on any error."""
        if not self.groq_api_key or not markdown.strip() or Groq is None:
            return []
        try:
            client = Groq(api_key=self.groq_api_key)
            resp = client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                messages=[{
                    "role": "user",
                    "content": (
                        "Extract ALL Vinted listings from this markdown as a JSON array. "
                        "Each item: {listing_id, title, price_raw, brand, size, condition, url, photo_url}. "
                        f"Return ONLY valid JSON array, no explanation.\n\n{markdown[:8000]}"
                    ),
                }],
                max_tokens=4096,
            )
            raw = resp.choices[0].message.content.strip()
            # Extract JSON if wrapped in markdown code block
            if "```" in raw:
                m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
                raw = m.group(1) if m else ""
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                return []
            return [self._build_item(item) for item in parsed]
        except Exception as e:
            logger.warning("llm_extract_failed", error=str(e))
            return []

    def _repair_schema(self, html: str, llm_items: list[dict]):
        """Attempt to repair the CSS baseSelector using Groq LLM."""
        try:
            if Groq is None or not self.groq_api_key:
                return
            client = Groq(api_key=self.groq_api_key)
            prompt = (
                "Given this HTML snippet, what is the best CSS selector to select "
                "individual product listing cards? Return ONLY the CSS selector string, "
                "nothing else.\n\nHTML (first 4000 chars):\n" + html[:4000]
            )
            resp = client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=64,
            )
            new_selector = resp.choices[0].message.content.strip().strip('"').strip("'")
            if not new_selector:
                return
            self.schema["baseSelector"] = new_selector
            with open(self.schema_path, "w", encoding="utf-8") as f:
                json.dump(self.schema, f, ensure_ascii=False, indent=2)
            logger.info("schema_repaired", new_selector=new_selector, schema_path=str(self.schema_path))
        except Exception as e:
            logger.warning("schema_repair_failed", error=str(e))

    def _normalize_price(self, raw) -> float | None:
        """Parse price strings like '25,00 €', '25.00 EUR', '25.00' → float.

        The LLM fallback sometimes returns price_raw already as a number, so
        accept int/float directly and coerce everything else via str()."""
        if raw is None or raw == "":
            return None
        if isinstance(raw, (int, float)):
            return float(raw)
        cleaned = re.sub(r"[€EUReur\s]", "", str(raw).replace(",", "."))
        m = re.search(r"[\d.]+", cleaned)
        if m:
            try:
                return float(m.group())
            except ValueError:
                return None
        return None

    def _normalize_condition(self, raw: str | None) -> str:
        """Map French condition strings to normalized keys."""
        if not raw:
            return "unknown"
        return _COND_MAP.get(raw.lower().strip(), "unknown")

    def _normalize_date(self, raw: str) -> str | None:
        """Normalize date strings to ISO YYYY-MM-DD."""
        if not raw:
            return None
        t = raw.strip().lower()
        today = date.today()
        if any(w in t for w in ("aujourd", "vandaag")):
            return today.strftime("%Y-%m-%d")
        if any(w in t for w in ("hier", "gisteren")):
            return (today - timedelta(days=1)).strftime("%Y-%m-%d")
        m = re.match(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})", t)
        if m:
            d_val, mo_val, yr_val = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if yr_val < 100:
                yr_val += 2000
            try:
                return date(yr_val, mo_val, d_val).strftime("%Y-%m-%d")
            except ValueError:
                pass
        return None

    def _validate(self, item: dict) -> bool:
        """Item is valid if title non-empty, price_eur > 0, and url non-empty."""
        return bool(item.get("title")) and (item.get("price_eur") or 0) > 0 and bool(item.get("url"))

    def _build_item(self, raw: dict) -> dict:
        """Convert raw field dict to normalized item dict."""
        price_eur = self._normalize_price(raw.get("price_raw", ""))
        return {
            "listing_id": raw.get("listing_id"),
            "title": raw.get("title", "").strip() or None,
            "price_eur": price_eur,
            "price_raw": raw.get("price_raw"),
            "brand": raw.get("brand"),
            "size": raw.get("size"),
            "condition": self._normalize_condition(raw.get("condition", "")),
            "url": raw.get("url"),
            "photo_url": raw.get("photo_url"),
        }
