"""Generate the site's design tokens from the visual identity.

Writes web/src/styles/tokens.css (CSS custom properties: light theme on :root, dark theme
under prefers-color-scheme) and web/src/lib/tokens.ts (the same values for TypeScript).
Both files are committed, so the site build does not depend on Python;
tests/test_web_tokens.py fails when they drift from identity.py. Regenerate with:
    uv run python scripts/make_web_tokens.py

The matplotlib type scale is in points for a fixed-size figure, so the web keeps only the
ratios between the sizes, expressed in rem relative to the label size (12 pt = 1 rem).
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
TS_PATH = WEB / "src" / "lib" / "tokens.ts"
HEADER = (
    "Generated from src/atlas_da_lavoura/viz/identity.py by scripts/make_web_tokens.py."
    " Do not edit by hand: run `uv run python scripts/make_web_tokens.py`."
)
FONT_STACK = f'"{vi.FONT_FAMILY}", system-ui, sans-serif'
BASE_PT = vi.TYPE_SCALE["label"]


def rem(points: int) -> str:
    value = f"{points / BASE_PT:.4f}".rstrip("0").rstrip(".")
    return f"{value}rem"


def theme_variables(theme: str) -> list[str]:
    lines = [f"  --color-background: {vi.BACKGROUND[theme]};"]
    lines += [f"  --color-{c.role.replace('_', '-')}: {c[theme]};" for c in vi.ALL_COLOURS]
    lines += [f"  --color-seq-{i}: {step};" for i, step in enumerate(vi.SEQUENTIAL[theme], start=1)]
    return lines


def render_css() -> str:
    out = [f"/* {HEADER} */", ":root {", f"  --font-sans: {FONT_STACK};"]
    out += [f"  --text-{name.replace('_', '-')}: {rem(pt)};" for name, pt in vi.TYPE_SCALE.items()]
    out += theme_variables("light")
    out += ["  color-scheme: light;", "}", "", "@media (prefers-color-scheme: dark) {", "  :root {"]
    out += [f"  {line}" for line in theme_variables("dark")]
    out += ["    color-scheme: dark;", "  }", "}", ""]
    return "\n".join(out)


def render_ts() -> str:
    data = {
        "fontFamily": vi.FONT_FAMILY,
        "fontStack": FONT_STACK,
        "typeScaleRem": {name: rem(pt) for name, pt in vi.TYPE_SCALE.items()},
        "themes": {
            theme: {
                "background": vi.BACKGROUND[theme],
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
    for path, content in ((CSS_PATH, render_css()), (TS_PATH, render_ts())):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
