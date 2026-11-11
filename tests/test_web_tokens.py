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


def test_fonts_css_matches_identity():
    generator = load_generator()
    assert generator.FONTS_CSS_PATH.read_text(encoding="utf-8") == generator.render_fonts_css(), (
        "web/src/styles/fonts.css drifted; run `uv run python scripts/make_web_tokens.py`"
    )


def test_every_typeface_weight_has_its_web_subset():
    generator = load_generator()
    vi = generator.vi
    css = generator.render_fonts_css()
    for face in vi.TYPEFACES:
        for weight, ttf in face.files:
            woff2 = generator.web_file(ttf)
            assert (generator.FONTS_DIR / woff2).is_file(), woff2
            assert f'url("/fonts/{woff2}")' in css
            assert f"font-weight: {weight};" in css
    assert (generator.FONTS_DIR / "license.txt").is_file()


def test_fluid_sizes_hit_both_ends():
    generator = load_generator()
    low, high = generator.vi.WEB_VIEWPORT_PX
    narrow, wide = 2.0, 3.25
    expression = generator.fluid(narrow, wide)
    preferred = expression.removeprefix("clamp(").split(", ")[1]
    intercept_rem, slope_vw = (part.strip() for part in preferred.split("+"))
    intercept = float(intercept_rem.removesuffix("rem"))
    slope = float(slope_vw.removesuffix("vw"))
    for viewport, expected in ((low, narrow), (high, wide)):
        size_px = intercept * generator.ROOT_PX + slope * viewport / 100
        assert abs(size_px - expected * generator.ROOT_PX) < 0.01


def test_tokens_cover_every_identity_colour():
    generator = load_generator()
    css = generator.render_css()
    vi = generator.vi
    for theme in vi.THEMES:
        assert f"--color-background: {vi.SITE_BACKGROUND[theme]};" in css
        assert f"--color-band: {vi.BAND[theme]};" in css
        for colour in vi.ALL_COLOURS:
            assert colour[theme] in css
        for step in vi.SEQUENTIAL[theme]:
            assert step in css
