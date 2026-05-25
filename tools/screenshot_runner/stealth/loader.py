from pathlib import Path


def load_stealth_script(session_seed: int = 42) -> str:
    """Load and prepare the stealth init script.

    Replaces __SESSION_SEED__ placeholder with the actual seed value.
    The seed should be consistent per session_id (e.g. hash of session_id).
    """
    js_path = Path(__file__).parent / "init.js"
    script = js_path.read_text(encoding="utf-8")
    return script.replace("__SESSION_SEED__", str(session_seed))


def session_seed_from_id(session_id: str) -> int:
    """Derive a consistent integer seed from a session_id string."""
    if not session_id:
        raise ValueError("session_id cannot be None or empty")
    return abs(hash(session_id)) % 10000
