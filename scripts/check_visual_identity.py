"""Validate the visual identity and render its reference images.

Checks every colour of src/atlas_da_lavoura/viz/identity.py against both backgrounds and
fails (exit 1) when a rule is broken:
- WCAG 2.x contrast: data colours >= 3:1 (graphical objects), text >= 4.5:1;
- colour-blind distinguishability: every pair of data colours must differ by at least
  MIN_DISTINCT_DELTA_E in CAM02-UCS (colorspacious)
  with normal vision and with each simulated deficiency (daltonlens: Viénot 1999 for
  protanopia and deuteranopia, Brettel 1997 for tritanopia, full severity);
- the sequential map ramp (monotonic, readable extremes, distinguishable neighbours);
- every bundled font file (family, SIL OFL, required characters, a plain zero after the
  face's OpenType features, I/l/1 apart, x-height, matplotlib weight selection).

Writes docs/img/identity_palette.png (swatches with name, hex, contrast and the simulated
colours) and, when the README chart exists, docs/img/identity_cvd_chart.png (the chart in
both themes as seen with each deficiency). Usage:
    uv run python scripts/check_visual_identity.py [--out docs/img]
"""

from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path

import matplotlib
import numpy as np
from colorspacious import deltaE
from daltonlens import simulate
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from atlas_da_lavoura.viz import identity as vi  # noqa: E402

DEFICIENCIES = {
    "deuteranopia": (simulate.Simulator_Vienot1999(), simulate.Deficiency.DEUTAN),
    "protanopia": (simulate.Simulator_Vienot1999(), simulate.Deficiency.PROTAN),
    "tritanopia": (simulate.Simulator_Brettel1997(), simulate.Deficiency.TRITAN),
}


def rgb(hex_colour: str) -> tuple[int, int, int]:
    return tuple(int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))


def luminance(hex_colour: str) -> float:
    def channel(v: int) -> float:
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(v) for v in rgb(hex_colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def simulate_image(pixels: np.ndarray, deficiency: str) -> np.ndarray:
    simulator, kind = DEFICIENCIES[deficiency]
    return simulator.simulate_cvd(pixels, kind, severity=1.0)


def simulate_colour(hex_colour: str, deficiency: str) -> str:
    out = simulate_image(np.array([[rgb(hex_colour)]], dtype=np.uint8), deficiency)[0, 0]
    return "#{:02x}{:02x}{:02x}".format(*(int(v) for v in out))


def distances(a: str, b: str) -> dict[str, float]:
    """CAM02-UCS distance with normal vision and with each simulated deficiency."""
    out = {"normal": float(deltaE(rgb(a), rgb(b), input_space="sRGB255"))}
    for name in DEFICIENCIES:
        sa, sb = simulate_colour(a, name), simulate_colour(b, name)
        out[name] = float(deltaE(rgb(sa), rgb(sb), input_space="sRGB255"))
    return out


def fmt(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def check() -> tuple[list[str], list[tuple]]:
    """Return the list of failures and the distance table rows."""
    failures, rows = [], []
    for theme in vi.THEMES:
        bg = vi.BACKGROUND[theme]
        for c in vi.ALL_COLOURS:
            if c.kind == "decoration":
                continue
            minimum = vi.MIN_GRAPHIC_CONTRAST if c.kind == "data" else vi.MIN_TEXT_CONTRAST
            value = contrast(c[theme], bg)
            if value < minimum:
                failures.append(f"{theme}: {c.role} contrast {value:.2f} < {minimum}")
        pairs = list(itertools.combinations(vi.DATA_COLOURS, 2))
        for a, b in pairs:
            d = distances(a[theme], b[theme])
            worst = min(d.values())
            required = (a.role, b.role) in vi.REQUIRED_DISTINCT_PAIRS
            rows.append((theme, a.role, b.role, d, worst, required))
            if worst < vi.MIN_DISTINCT_DELTA_E:
                failures.append(f"{theme}: {a.role} x {b.role} min ΔE {worst:.1f}")
        failures.extend(check_sequential(theme, rows))
    failures.extend(check_site_backgrounds()[0])
    failures.extend(check_typefaces()[0])
    return failures, rows


def check_site_backgrounds() -> tuple[list[str], list[tuple]]:
    """The site's page and band backgrounds: text on both, data and map ramp on the page."""
    failures, rows = [], []
    for theme in vi.THEMES:
        for surface, backgrounds in (("site", vi.SITE_BACKGROUND), ("band", vi.BAND)):
            bg = backgrounds[theme]
            for c in vi.ALL_COLOURS:
                if c.kind == "decoration" or (c.kind == "data" and surface == "band"):
                    continue
                minimum = vi.MIN_GRAPHIC_CONTRAST if c.kind == "data" else vi.MIN_TEXT_CONTRAST
                value = contrast(c[theme], bg)
                rows.append((theme, surface, c.role, value, minimum))
                if value < minimum:
                    failures.append(f"{theme} {surface}: {c.role} contrast {value:.2f} < {minimum}")
        strong = contrast(vi.SEQUENTIAL[theme][-1], vi.SITE_BACKGROUND[theme])
        rows.append((theme, "site", "sequential end", strong, vi.MIN_GRAPHIC_CONTRAST))
        if strong < vi.MIN_GRAPHIC_CONTRAST:
            failures.append(f"{theme} site: sequential strong end contrast {strong:.2f}")
    return failures, rows


def _single_substitutions(font: TTFont, tag: str) -> dict[str, str]:
    table = font["GSUB"].table
    mapping: dict[str, str] = {}
    for record in table.FeatureList.FeatureRecord:
        if record.FeatureTag != tag:
            continue
        for index in record.Feature.LookupListIndex:
            for sub in table.LookupList.Lookup[index].SubTable:
                sub = getattr(sub, "ExtSubTable", sub)
                mapping.update(getattr(sub, "mapping", None) or {})
    return mapping


def _outline(font: TTFont, glyph: str) -> tuple:
    glyph_set = font.getGlyphSet()
    pen = DecomposingRecordingPen(glyph_set)
    glyph_set[glyph].draw(pen)
    return tuple(pen.value)


def check_typefaces() -> tuple[list[str], list[tuple]]:
    """Every bundled font file: the rules the IBM Plex Sans was chosen by, now automated."""
    from matplotlib import font_manager

    vi.register_fonts()
    failures, rows = [], []
    for face in vi.TYPEFACES:
        for weight, name in face.files:
            path = vi.FONT_DIR / name
            if not path.is_file():
                failures.append(f"{name}: file missing")
                continue
            font = TTFont(path)
            names, cmap = font["name"], font.getBestCmap()
            family = names.getDebugName(16) or names.getDebugName(1)
            if family != face.family:
                failures.append(f"{name}: family {family!r}, expected {face.family!r}")
            if "SIL Open Font License" not in (names.getDebugName(13) or ""):
                failures.append(f"{name}: licence is not the SIL OFL")
            missing = [c for c in vi.REQUIRED_CHARACTERS if ord(c) not in cmap]
            if missing:
                failures.append(f"{name}: missing characters {''.join(missing)}")
            zero = cmap[ord("0")]
            for tag in face.features:
                zero = _single_substitutions(font, tag).get(zero, zero)
            zero_contours = sum(1 for op, _ in _outline(font, zero) if op == "closePath")
            if zero_contours != 2:
                failures.append(f"{name}: the zero ({zero}) is marked ({zero_contours} contours)")
            outlines = {c: _outline(font, cmap[ord(c)]) for c in "Il1"}
            if len(set(outlines.values())) < len(outlines):
                failures.append(f"{name}: I, l and 1 are not all different")
            x_height = font["OS/2"].sxHeight / font["head"].unitsPerEm
            if x_height < vi.MIN_X_HEIGHT_EM:
                failures.append(f"{name}: x-height {x_height:.3f} em < {vi.MIN_X_HEIGHT_EM}")
            chosen = font_manager.findfont(
                font_manager.FontProperties(family=face.family, weight=weight),
                fallback_to_default=False,
            )
            if Path(chosen).name != name:
                failures.append(f"{name}: matplotlib picks {Path(chosen).name} for {weight}")
            rows.append((face.role, name, names.getDebugName(5), x_height, zero, zero_contours))
    face, weight = vi.DISPLAY_NUMBER
    if weight not in {w for w, _ in face.files}:
        failures.append(f"display number: {face.family} has no bundled weight {weight}")
    return failures, rows


def check_sequential(theme: str, rows: list[tuple]) -> list[str]:
    """The choropleth ramp: monotonic, readable extremes, distinguishable neighbours."""
    failures = []
    bg = vi.BACKGROUND[theme]
    steps = vi.SEQUENTIAL[theme]
    lums = [luminance(s) for s in steps]
    deltas = [b - a for a, b in itertools.pairwise(lums)]
    if not (all(d < 0 for d in deltas) or all(d > 0 for d in deltas)):
        failures.append(f"{theme}: sequential luminance is not monotonic")
    extremes = contrast(steps[0], steps[-1])
    if extremes < vi.MIN_TEXT_CONTRAST:
        failures.append(f"{theme}: sequential extremes contrast {extremes:.2f}")
    strong = contrast(steps[-1], bg)
    if strong < vi.MIN_GRAPHIC_CONTRAST:
        failures.append(f"{theme}: sequential strong end contrast {strong:.2f}")
    for i, (a, b) in enumerate(itertools.pairwise(steps), start=1):
        d = distances(a, b)
        worst = min(d.values())
        rows.append((theme, f"seq{i}", f"seq{i + 1}", d, worst, False))
        if worst < vi.MIN_DISTINCT_DELTA_E:
            failures.append(f"{theme}: sequential step {i} x {i + 1} min ΔE {worst:.1f}")
    return failures


def render_swatch(out: Path) -> None:
    vi.register_fonts()
    plt.rcParams.update({"font.family": vi.FONT_FAMILY})
    colours = [c for c in vi.ALL_COLOURS if c.kind != "decoration"]
    fig, axes = plt.subplots(1, 2, figsize=(14, 0.62 * len(colours) + 1.3), dpi=150)
    for ax, theme in zip(axes, vi.THEMES, strict=True):
        p = vi.palette(theme)
        bg = p["background"]
        ax.add_patch(plt.Rectangle((0, 0), 1, 1, transform=ax.transAxes, color=bg, zorder=0))
        ax.set_xlim(0, 10)
        ax.set_ylim(len(colours) + 0.4, -1.1)
        ax.axis("off")
        label = "Tema claro (#ffffff)" if theme == "light" else "Tema escuro (#0d1117)"
        ax.text(0.1, -0.6, label, fontsize=15, fontweight="bold", color=p["text"], va="center")
        for x, head in ((6.35, "normal"), (7.25, "deut."), (8.15, "prot."), (9.05, "trit.")):
            ax.text(x, 0.05, head, fontsize=9.5, color=p["text_muted"], ha="center", va="center")
        for i, c in enumerate(colours, start=1):
            hex_colour = c[theme]
            ax.add_patch(plt.Rectangle((0.1, i - 0.38), 1.3, 0.76, color=hex_colour))
            minimum = vi.MIN_GRAPHIC_CONTRAST if c.kind == "data" else vi.MIN_TEXT_CONTRAST
            value = contrast(hex_colour, bg)
            ax.text(1.65, i - 0.13, c.name_pt, fontsize=13, color=p["text"], va="center")
            ax.text(
                1.65,
                i + 0.2,
                f"{hex_colour}   contraste {fmt(value)}:1 (mín. {fmt(minimum, 1)}:1)",
                fontsize=10.5,
                color=p["text_secondary"],
                va="center",
            )
            for x, sim in (
                (6.35, None),
                (7.25, "deuteranopia"),
                (8.15, "protanopia"),
                (9.05, "tritanopia"),
            ):
                shown = hex_colour if sim is None else simulate_colour(hex_colour, sim)
                ax.add_patch(plt.Rectangle((x - 0.38, i - 0.3), 0.76, 0.6, color=shown))
    fig.patch.set_facecolor("#808080")
    fig.subplots_adjust(left=0.004, right=0.996, top=0.995, bottom=0.005, wspace=0.01)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor="#808080")
    plt.close(fig)
    print(f"wrote {out}")


def render_cvd_chart(charts: dict[str, Path], out: Path, width: int = 700) -> None:
    font_path = str(vi.FONT_DIR / vi.FONT_FILES[1])
    font = ImageFont.truetype(font_path, 22)
    columns = ["original", *DEFICIENCIES]
    tiles = {}
    for theme, path in charts.items():
        img = Image.open(path).convert("RGB")
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
        pixels = np.asarray(img)
        tiles[theme] = [img] + [Image.fromarray(simulate_image(pixels, d)) for d in DEFICIENCIES]
    tile_h = next(iter(tiles.values()))[0].height
    header, gap = 40, 12
    canvas = Image.new(
        "RGB",
        (len(columns) * width + (len(columns) - 1) * gap, len(tiles) * (tile_h + header + gap)),
        (128, 128, 128),
    )
    draw = ImageDraw.Draw(canvas)
    for r, theme in enumerate(tiles):
        y = r * (tile_h + header + gap)
        for k, name in enumerate(columns):
            x = k * (width + gap)
            title = f"{'claro' if theme == 'light' else 'escuro'}: {name}"
            draw.text((x + 6, y + 8), title, fill=(255, 255, 255), font=font)
            canvas.paste(tiles[theme][k], (x, y + header))
    canvas.save(out, optimize=True)
    print(f"wrote {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default="docs/img", help="output folder (default: docs/img)")
    args = parser.parse_args()
    out = Path(args.out)

    failures, rows = check()
    print("min CAM02-UCS ΔE (normal / deuteranopia / protanopia / tritanopia), required pairs *")
    for theme, a, b, d, worst, required in rows:
        values = " / ".join(f"{v:5.1f}" for v in d.values())
        print(f"  {theme:5s} {a:8s} x {b:8s} {values}   min {worst:5.1f}{' *' if required else ''}")
    print("site backgrounds (theme, surface, colour, contrast, minimum)")
    for theme, surface, role, value, minimum in check_site_backgrounds()[1]:
        print(f"  {theme:5s} {surface:4s} {role:15s} {value:5.2f}:1 (min {minimum})")
    print("typefaces (role, file, version, x-height, zero glyph, zero contours)")
    for role, name, version, x_height, zero, contours in check_typefaces()[1]:
        print(f"  {role:8s} {name:28s} {version:14s} x {x_height:.3f} em  {zero} ({contours})")
    render_swatch(out / "identity_palette.png")
    charts = {t: out / f"soybean_yield_anomaly_rs_{t}.png" for t in vi.THEMES}
    if all(p.exists() for p in charts.values()):
        render_cvd_chart(charts, out / "identity_cvd_chart.png")
    if failures:
        print("FAILED:\n  " + "\n  ".join(failures))
        raise SystemExit(1)
    print("all identity checks passed")


if __name__ == "__main__":
    main()
