"""Generate the site's design tokens from the visual identity.

Writes, from src/atlas_da_lavoura/viz/identity.py:
- web/src/styles/tokens.css: CSS custom properties (light theme on :root, dark theme under
  prefers-color-scheme), the three font stacks and the site type scale;
- web/src/styles/fonts.css: one @font-face per typeface weight, pointing at the Latin1 woff2
  subsets in web/public/fonts/ with IBM's official unicode-range for each family;
- web/src/lib/tokens.ts: the same values for TypeScript.
The files are committed, so the site build does not depend on Python;
tests/test_web_tokens.py fails when they drift from identity.py. Regenerate with:
    uv run python scripts/make_web_tokens.py

The matplotlib type scale is in points for a fixed-size figure, so the web keeps only the
ratios between the sizes, expressed in rem relative to the label size (12 pt = 1 rem). The
site scale (WEB_TYPE_SCALE) becomes clamp() expressions that grow linearly between the two
viewport widths of WEB_VIEWPORT_PX.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from atlas_da_lavoura.viz import identity as vi  # noqa: E402

WEB = ROOT / "web"
CSS_PATH = WEB / "src" / "styles" / "tokens.css"
FONTS_CSS_PATH = WEB / "src" / "styles" / "fonts.css"
TS_PATH = WEB / "src" / "lib" / "tokens.ts"
FONTS_DIR = WEB / "public" / "fonts"
HEADER = (
    "Generated from src/atlas_da_lavoura/viz/identity.py by scripts/make_web_tokens.py."
    " Do not edit by hand: run `uv run python scripts/make_web_tokens.py`."
)
FALLBACKS = {
    "text": "system-ui, sans-serif",
    "titles": "Georgia, serif",
    "numbers": "ui-monospace, monospace",
}
CSS_NAMES = {"text": "sans", "titles": "serif", "numbers": "mono"}
# IBM's official Latin1 unicode-range for each family, from the CSS shipped in the releases
# named in identity.py (css/ibm-plex-<family>-default.min.css).
LATIN1_COMMON = (
    "U+0020-007E, U+00A0-00FF, U+0131, U+0152-0153, U+02C6, U+02DA, U+02DC, U+2013-2014,"
    " U+2018-201A, U+201C-201E, U+2020-2022, U+2026, U+2030, U+2039-203A, U+2044, U+20AC,"
    " U+2122, U+2212, U+FB01-FB02"
)
UNICODE_RANGE = {
    "IBM Plex Sans": (
        "U+0000, U+000D, U+0020-007E, U+00A0-00A3, U+00A4-00FF, U+0131, U+0152-0153, U+02C6,"
        " U+02DA, U+02DC, U+2013-2014, U+2018-201A, U+201C-201E, U+2020-2022, U+2026, U+2030,"
        " U+2039-203A, U+2044, U+2074, U+20AC, U+2122, U+2212, U+FB01-FB02"
    ),
    "IBM Plex Serif": LATIN1_COMMON,
    "IBM Plex Mono": LATIN1_COMMON,
}
BASE_PT = vi.TYPE_SCALE["label"]
ROOT_PX = 16


def number(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


def rem(points: int) -> str:
    return f"{number(points / BASE_PT)}rem"


def fluid(narrow: float, wide: float) -> str:
    """clamp() growing linearly from `narrow` rem to `wide` rem across WEB_VIEWPORT_PX."""
    low, high = vi.WEB_VIEWPORT_PX
    slope = (wide - narrow) * ROOT_PX / (high - low)  # px of font per px of viewport
    intercept = narrow - slope * low / ROOT_PX
    preferred = f"{number(intercept)}rem + {number(slope * 100)}vw"
    return f"clamp({number(narrow)}rem, {preferred}, {number(wide)}rem)"


def stack(face: vi.Typeface) -> str:
    return f'"{face.family}", {FALLBACKS[face.role]}'


def features(face: vi.Typeface) -> str:
    return ", ".join(f'"{tag}"' for tag in face.features) or "normal"


def web_file(ttf: str) -> str:
    return ttf.removesuffix(".ttf") + "-Latin1.woff2"


def theme_variables(theme: str) -> list[str]:
    lines = [
        f"  --color-background: {vi.SITE_BACKGROUND[theme]};",
        f"  --color-band: {vi.BAND[theme]};",
    ]
    lines += [f"  --color-{c.role.replace('_', '-')}: {c[theme]};" for c in vi.ALL_COLOURS]
    lines += [f"  --color-seq-{i}: {step};" for i, step in enumerate(vi.SEQUENTIAL[theme], start=1)]
    return lines


def render_css() -> str:
    out = [f"/* {HEADER} */", ":root {"]
    for face in vi.TYPEFACES:
        name = CSS_NAMES[face.role]
        out += [f"  --font-{name}: {stack(face)};", f"  --font-{name}-features: {features(face)};"]
    display_face, display_weight = vi.DISPLAY_NUMBER
    out += [
        f"  --font-display-number: {stack(display_face)};",
        f"  --font-display-number-weight: {display_weight};",
    ]
    out += [f"  --text-{name.replace('_', '-')}: {rem(pt)};" for name, pt in vi.TYPE_SCALE.items()]
    out += [f"  --size-{role}: {fluid(*sizes)};" for role, sizes in vi.WEB_TYPE_SCALE.items()]
    out += theme_variables("light")
    out += ["  color-scheme: light;", "}", "", "@media (prefers-color-scheme: dark) {", "  :root {"]
    out += [f"  {line}" for line in theme_variables("dark")]
    out += ["    color-scheme: dark;", "  }", "}", ""]
    return "\n".join(out)


def render_fonts_css() -> str:
    out = [
        f"/* {HEADER} */",
        "/* Latin1 subsets of IBM Plex (SIL OFL 1.1, public/fonts/license.txt). */",
    ]
    for face in vi.TYPEFACES:
        for weight, ttf in face.files:
            out += [
                "",
                "@font-face {",
                f'  font-family: "{face.family}";',
                "  font-style: normal;",
                f"  font-weight: {weight};",
                "  font-display: swap;",
                f'  src: url("/fonts/{web_file(ttf)}") format("woff2");',
                f"  unicode-range: {UNICODE_RANGE[face.family]};",
                "}",
            ]
    return "\n".join(out) + "\n"


def render_ts() -> str:
    data = {
        "fontFamily": vi.FONT_FAMILY,
        "fontStack": stack(vi.TEXT_FACE),
        "typefaces": {
            face.role: {
                "family": face.family,
                "stack": stack(face),
                "features": list(face.features),
                "files": [{"weight": w, "url": f"/fonts/{web_file(ttf)}"} for w, ttf in face.files],
                "unicodeRange": UNICODE_RANGE[face.family],
            }
            for face in vi.TYPEFACES
        },
        "displayNumber": {"role": vi.DISPLAY_NUMBER[0].role, "weight": vi.DISPLAY_NUMBER[1]},
        "typeScaleRem": {name: rem(pt) for name, pt in vi.TYPE_SCALE.items()},
        "webTypeScale": {role: fluid(*sizes) for role, sizes in vi.WEB_TYPE_SCALE.items()},
        "themes": {
            theme: {
                "background": vi.SITE_BACKGROUND[theme],
                "band": vi.BAND[theme],
                **{c.role: c[theme] for c in vi.ALL_COLOURS},
                "sequential": list(vi.SEQUENTIAL[theme]),
            }
            for theme in vi.THEMES
        },
    }
    body = json.dumps(data, indent=2, ensure_ascii=False)
    return (
        f"// {HEADER}\n"
        f"export const tokens = {body} as const;\n\n"
        "export type Theme = keyof typeof tokens.themes;\n"
    )


def main() -> None:
    for path, content in (
        (CSS_PATH, render_css()),
        (FONTS_CSS_PATH, render_fonts_css()),
        (TS_PATH, render_ts()),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
