"""Unit tests for FlipScorer."""
from __future__ import annotations

import pytest
from tools.decision_agent.scorer import FlipScorer


def _stats(median=400.0, avg_sell_days=None, sell_days_sample=5):
    return {
        "median_price": median,
        "avg_sell_days": avg_sell_days,
        "sell_days_sample": sell_days_sample,
    }


# price 200, median 400 → price_ratio = 0.50 < 0.70
# fees = 200 * 0.12 + 15 = 39; margin_eur = 400 - 200 - 39 = 161; margin_pct = 0.805 > 0.25 → BUY
def test_buy_decision():
    scorer = FlipScorer()
    result = scorer.score(200.0, _stats(median=400.0))
    assert result["decision"] == "BUY"


# price 300, median 400 → price_ratio = 0.75 (between 0.70 and 0.85)
# fees = 300 * 0.12 + 15 = 51; margin_eur = 400 - 300 - 51 = 49; margin_pct = 0.163 > 0.15 → OFFER
def test_offer_decision():
    scorer = FlipScorer()
    result = scorer.score(300.0, _stats(median=400.0))
    assert result["decision"] == "OFFER"


# price 390, median 400 → price_ratio = 0.975 >= 0.85
# fees = 390 * 0.12 + 15 = 61.8; margin_eur = 400 - 390 - 61.8 = -51.8 → SKIP
def test_skip_decision():
    scorer = FlipScorer()
    result = scorer.score(390.0, _stats(median=400.0))
    assert result["decision"] == "SKIP"


def test_skip_when_median_none():
    scorer = FlipScorer()
    result = scorer.score(200.0, {"median_price": None})
    assert result["decision"] == "SKIP"
    assert result["confidence"] == 0.0
    assert result["reasoning"] == "no market data"


def test_confidence_decreases_slow_velocity():
    scorer = FlipScorer()
    r_normal = scorer.score(200.0, _stats(avg_sell_days=14.0))  # normal velocity
    r_slow = scorer.score(200.0, _stats(avg_sell_days=30.0))    # slow velocity
    assert r_slow["confidence"] < r_normal["confidence"]


def test_confidence_increases_fast_velocity():
    scorer = FlipScorer()
    r_normal = scorer.score(200.0, _stats(avg_sell_days=14.0))  # normal velocity
    r_fast = scorer.score(200.0, _stats(avg_sell_days=3.0))     # fast velocity
    assert r_fast["confidence"] > r_normal["confidence"]


def test_confidence_malus_avg_sell_days_null():
    scorer = FlipScorer()
    r_known = scorer.score(200.0, _stats(avg_sell_days=10.0))
    r_null = scorer.score(200.0, _stats(avg_sell_days=None))
    assert r_null["confidence"] < r_known["confidence"]


def test_confidence_malus_sell_days_sample_low():
    scorer = FlipScorer()
    r_good = scorer.score(200.0, _stats(sell_days_sample=10))
    r_low = scorer.score(200.0, _stats(sell_days_sample=2))
    assert r_low["confidence"] < r_good["confidence"]


def test_margin_eur_correct():
    scorer = FlipScorer(shipping_estimate=15.0, ebay_fee_rate=0.12)
    result = scorer.score(200.0, _stats(median=400.0))
    # fees = 200 * 0.12 + 15 = 39; margin_eur = 400 - 200 - 39 = 161
    assert result["margin_eur"] == pytest.approx(161.0, abs=0.01)


def test_margin_pct_correct():
    scorer = FlipScorer(shipping_estimate=15.0, ebay_fee_rate=0.12)
    result = scorer.score(200.0, _stats(median=400.0))
    # margin_pct = 161 / 200 = 0.805
    assert result["margin_pct"] == pytest.approx(0.805, abs=0.001)


def test_price_ratio_correct():
    scorer = FlipScorer()
    result = scorer.score(200.0, _stats(median=400.0))
    assert result["price_ratio"] == pytest.approx(0.50, abs=0.001)


def test_score_batch_sorted_by_confidence():
    scorer = FlipScorer()
    stats = _stats(median=400.0)
    items = [
        {"price_value": 200.0, "epid": "E1"},  # BUY, high confidence
        {"price_value": 300.0, "epid": "E2"},  # OFFER, lower confidence
    ]
    results = scorer.score_batch(items, stats)
    confidences = [r["confidence"] for r in results]
    assert confidences == sorted(confidences, reverse=True)


def test_score_batch_filters_no_epid():
    scorer = FlipScorer()
    stats = _stats(median=400.0)
    items = [
        {"price_value": 200.0, "epid": "E1"},
        {"price_value": 200.0, "epid": None},   # should be skipped
        {"price_value": 200.0, "epid": ""},     # should be skipped
    ]
    results = scorer.score_batch(items, stats)
    assert len(results) == 1


def test_reasoning_not_empty():
    scorer = FlipScorer()
    result = scorer.score(200.0, _stats(median=400.0))
    assert result["reasoning"]
    assert len(result["reasoning"]) > 0


def test_value_error_on_zero_price():
    scorer = FlipScorer()
    with pytest.raises(ValueError):
        scorer.score(0.0, _stats(median=400.0))
