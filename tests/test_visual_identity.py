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
