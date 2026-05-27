"""Tests pour EbayTokenManager."""
import time
import pytest
from unittest.mock import MagicMock, patch
from tools.scrapy_runner.ebay_auth import EbayTokenManager


def make_manager(n_keys=1):
    app_ids = [f"app_{i}" for i in range(n_keys)]
    cert_ids = [f"cert_{i}" for i in range(n_keys)]
    return EbayTokenManager(app_ids, cert_ids)


def _mock_post_response(token: str) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {"access_token": token}
    resp.raise_for_status.return_value = None
    return resp


def test_get_token_returns_token():
    """get_token() retourne un token valide (mock OAuth2)."""
    with patch("requests.post", return_value=_mock_post_response("tok_abc")) as mock_post:
        mgr = make_manager()
        assert mgr.get_token(0) == "tok_abc"
        assert mock_post.call_count == 1


def test_get_token_cached():
    """2e appel = pas de requête HTTP (cache)."""
    with patch("requests.post", return_value=_mock_post_response("tok_xyz")) as mock_post:
        mgr = make_manager()
        mgr.get_token(0)
        mgr.get_token(0)
        assert mock_post.call_count == 1


def test_get_token_refresh_on_expiry():
    """Token expiré → nouveau fetch."""
    responses = [_mock_post_response("tok_1"), _mock_post_response("tok_2")]
    with patch("requests.post", side_effect=responses) as mock_post:
        mgr = make_manager()
        mgr._TOKEN_TTL = -1  # force expiry immédiate
        mgr.get_token(0)
        tok2 = mgr.get_token(0)
        assert mock_post.call_count == 2
        assert tok2 == "tok_2"


def test_pick_key_returns_least_used():
    """pick_key() retourne la clé la moins utilisée."""
    mgr = make_manager(n_keys=3)
    mgr.record_call(0)
    mgr.record_call(0)
    mgr.record_call(1)
    assert mgr.pick_key() == 2  # clé 2 n'a aucun appel


def test_record_call_increments():
    """record_call() incrémente le compteur."""
    mgr = make_manager()
    assert mgr.calls_today(0) == 0
    mgr.record_call(0)
    mgr.record_call(0)
    assert mgr.calls_today(0) == 2


def test_daily_limit_raises():
    """DAILY_LIMIT atteint → KeyError."""
    mgr = make_manager()
    today = mgr._today()
    mgr._calls[0] = {today: EbayTokenManager.DAILY_LIMIT}
    with pytest.raises(KeyError):
        mgr.pick_key()


def test_rotation_three_keys():
    """Avec 3 clés, pick_key() round-robins vers la moins utilisée."""
    mgr = make_manager(n_keys=3)
    for _ in range(5):
        mgr.record_call(0)
    for _ in range(3):
        mgr.record_call(1)
    # clé 2 est la moins utilisée
    assert mgr.pick_key() == 2


def test_calls_today_zero_at_startup():
    """calls_today() retourne 0 sans aucun appel."""
    mgr = make_manager()
    assert mgr.calls_today(0) == 0
