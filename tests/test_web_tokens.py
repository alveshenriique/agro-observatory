"""The committed web tokens must match what identity.py generates (drift check)."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "make_web_tokens.py"


def load_generator():
    spec = importlib.util.spec_from_file_location("make_web_tokens", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tokens_css_matches_identity():
    generator = load_generator()
    assert generator.CSS_PATH.read_text(encoding="utf-8") == generator.render_css(), (
        "web/src/styles/tokens.css drifted; run `uv run python scripts/make_web_tokens.py`"
    )


def test_tokens_ts_matches_identity():
    generator = load_generator()
    assert generator.TS_PATH.read_text(encoding="utf-8") == generator.render_ts(), (
        "web/src/lib/tokens.ts drifted; run `uv run python scripts/make_web_tokens.py`"
    )


def test_tokens_cover_every_identity_colour():
    generator = load_generator()
    css = generator.render_css()
    vi = generator.vi
    for theme in vi.THEMES:
        for colour in vi.ALL_COLOURS:
            assert colour[theme] in css
        for step in vi.SEQUENTIAL[theme]:
            assert step in css
