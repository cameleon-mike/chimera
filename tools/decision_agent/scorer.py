"""FlipScorer — FLIPMACHINE buy/offer/skip scoring engine."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class FlipScorer:
    def __init__(self, shipping_estimate: float = 15.0, ebay_fee_rate: float = 0.12):
        self.shipping_estimate = shipping_estimate
        self.ebay_fee_rate = ebay_fee_rate

    def score(self, listed_price: float, epid_stats: dict) -> dict:
        """Score a single item against market data.

        Args:
            listed_price: The asking price for the item
            epid_stats: Dictionary containing market statistics (at minimum: median_price, avg_sell_days, sell_days_sample)

        Returns:
            Dictionary with keys: decision, confidence, price_ratio, margin_eur, margin_pct, velocity_flag, reasoning
        """
        if listed_price <= 0:
            raise ValueError("listed_price must be positive")

        median_price = epid_stats.get("median_price")
        if median_price is None:
            return {
                "decision": "SKIP",
                "confidence": 0.0,
                "price_ratio": None,
                "margin_eur": None,
                "margin_pct": None,
                "velocity_flag": "unknown",
                "reasoning": "no market data",
            }

        avg_sell_days = epid_stats.get("avg_sell_days")
        sell_days_sample = (epid_stats.get("sell_days_sample") or 0) or 0

        price_ratio = listed_price / median_price
        fees = listed_price * self.ebay_fee_rate + self.shipping_estimate
        margin_eur = median_price - listed_price - fees
        margin_pct = margin_eur / listed_price

        velocity_flag = self._velocity_flag(avg_sell_days)
        confidence = self._confidence(price_ratio, velocity_flag, sell_days_sample, avg_sell_days)

        # Decision logic
        if price_ratio < 0.70 and margin_pct > 0.25:
            decision = "BUY"
        elif price_ratio < 0.85 and margin_pct > 0.15:
            decision = "OFFER"
        else:
            decision = "SKIP"

        # Reasoning
        if decision == "BUY":
            reasoning = f"Listed at {price_ratio:.0%} of median — strong margin potential"
        elif decision == "OFFER":
            reasoning = f"Listed at {price_ratio:.0%} of median — moderate margin potential"
        else:
            reasoning = f"Listed at {price_ratio:.0%} of median — insufficient margin"

        return {
            "decision": decision,
            "confidence": confidence,
            "price_ratio": price_ratio,
            "margin_eur": margin_eur,
            "margin_pct": margin_pct,
            "velocity_flag": velocity_flag,
            "reasoning": reasoning,
        }

    def _velocity_flag(self, avg_sell_days: float | None) -> str:
        """Classify velocity based on average sell days."""
        if avg_sell_days is None:
            return "unknown"
        if avg_sell_days < 7:
            return "fast"
        if avg_sell_days <= 21:
            return "normal"
        return "slow"

    def _confidence(self, price_ratio: float, velocity_flag: str, sell_days_sample: int, avg_sell_days: float | None) -> float:
        """Calculate confidence score based on multiple factors."""
        # Base from price_ratio
        if price_ratio < 0.65:
            base = 0.85
        elif price_ratio < 0.80:
            base = 0.70
        elif price_ratio < 0.95:
            base = 0.50
        else:
            base = 0.30

        modifiers = 0.0

        # Velocity modifiers
        if velocity_flag == "fast":
            modifiers += 0.10
        elif velocity_flag == "slow":
            modifiers -= 0.10

        # Data quality modifiers
        if avg_sell_days is None:
            modifiers -= 0.15
        if sell_days_sample < 3:
            modifiers -= 0.20

        return max(0.0, min(1.0, base + modifiers))

    def score_batch(self, items: list[dict], epid_stats: dict) -> list[dict]:
        """Score multiple items against the same market data.

        Args:
            items: List of dicts with at least 'price_value' (float) and 'epid' (str) keys
            epid_stats: Single stats dict applied uniformly to all items

        Returns:
            Sorted list of scored items (by confidence descending), merged with original item data
        """
        scored = []

        for item in items:
            epid = item.get("epid")
            # Skip items with no epid
            if not epid:
                continue

            price_value = item.get("price_value")
            # Skip items with no valid price
            if price_value is None or price_value <= 0:
                continue

            result = self.score(price_value, epid_stats)

            # Merge result into a copy of the item
            scored_item = dict(item)
            scored_item.update(result)
            scored.append(scored_item)

        # Sort by confidence descending
        scored.sort(key=lambda x: x["confidence"], reverse=True)

        return scored
