"""The visual identity must keep passing its contrast and colour-blind checks."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_visual_identity.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("check_visual_identity", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_identity_passes_contrast_and_colour_blind_checks():
    failures, rows = load_checker().check()
    assert failures == []
    assert rows, "no colour pairs were checked"


def test_required_pairs_are_checked_in_both_themes():
    _, rows = load_checker().check()
    checked = {(theme, a, b) for theme, a, b, _, _, required in rows if required}
    assert checked == {
        (theme, a, b)
        for theme in ("light", "dark")
        for a, b in (("dry", "neutral"), ("hot", "cold"))
    }


def test_bundled_font_files_exist():
    from atlas_da_lavoura.viz import identity

    for name in (*identity.FONT_FILES, "OFL.txt"):
        assert (identity.FONT_DIR / name).is_file(), name


def test_typefaces_pass_their_checks():
    failures, rows = load_checker().check_typefaces()
    assert failures == []
    assert {role for role, *_ in rows} == {"text", "titles", "numbers"}


def test_site_backgrounds_are_checked_in_both_themes():
    failures, rows = load_checker().check_site_backgrounds()
    assert failures == []
    assert {(theme, surface) for theme, surface, *_ in rows} == {
        (theme, surface) for theme in ("light", "dark") for surface in ("site", "band")
    }


def test_site_background_check_catches_low_contrast(monkeypatch):
    checker = load_checker()
    monkeypatch.setattr(checker.vi, "BAND", {"light": "#8a8a8a", "dark": "#1f1b16"})
    failures, _ = checker.check_site_backgrounds()
    assert any(failure.startswith("light band: text") for failure in failures)


def test_typeface_check_catches_the_dotted_mono_zero(monkeypatch):
    checker = load_checker()
    face = checker.vi.NUMBER_FACE
    without_ss04 = checker.vi.Typeface(
        face.role, face.name_pt, face.family, face.files, (), face.release
    )
    monkeypatch.setattr(checker.vi, "TYPEFACES", (without_ss04,))
    failures, _ = checker.check_typefaces()
    assert any("zero" in failure and "marked" in failure for failure in failures)
