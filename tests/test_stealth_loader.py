def test_seed_replaced_in_script():
    from tools.screenshot_runner.stealth.loader import load_stealth_script
    script = load_stealth_script(session_seed=42)
    assert "__SESSION_SEED__" not in script
    assert "42" in script


def test_seed_rejects_none():
    from tools.screenshot_runner.stealth.loader import session_seed_from_id
    import pytest
    with pytest.raises(ValueError):
        session_seed_from_id(None)


def test_seed_rejects_empty_string():
    from tools.screenshot_runner.stealth.loader import session_seed_from_id
    import pytest
    with pytest.raises(ValueError):
        session_seed_from_id("")


def test_session_seed_from_id_deterministic():
    from tools.screenshot_runner.stealth.loader import session_seed_from_id
    s1 = session_seed_from_id("sess_abc")
    s2 = session_seed_from_id("sess_abc")
    assert s1 == s2


def test_session_seed_different_ids():
    from tools.screenshot_runner.stealth.loader import session_seed_from_id
    s1 = session_seed_from_id("sess_abc")
    s2 = session_seed_from_id("sess_xyz")
    assert s1 != s2
