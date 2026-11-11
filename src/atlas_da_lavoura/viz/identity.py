"""Visual identity of the project: colours, typography and the matplotlib style.

This module is the single source of the identity. The README chart uses it through
`apply_style`, `scripts/check_visual_identity.py` validates it (WCAG contrast on both
backgrounds and colour-blind distinguishability) and the future Power BI theme should be
generated from `as_dict()`. Choices and their justification are in docs/DECISOES.md,
section "Identidade visual".

Data colours come from the IPCC AR6 WGI colour scales (github.com/IPCC-WG1/colormaps):
dry and wet from the precipitation divergent scale (brown to blue-green), hot and cold from
the temperature divergent scale (red to blue). Each role has a light-theme variant for a
#ffffff background and a dark-theme variant for #0d1117 (the GitHub page colours), picked
along the same official scale. Indices refer to the 256-step continuous files
(`prec_div.txt`, `temp_div.txt`, 0 = first line). There is no accent colour: every colour
either encodes data or is text, so emphasis comes only from the data (the dry brown) and
from weight (bold).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

THEMES = ("light", "dark")
# Backgrounds of the charts made for GitHub (the README), the page colours there.
BACKGROUND = {"light": "#ffffff", "dark": "#0d1117"}
# The site sits on a warm white, the paper of the approved page drafts; highlight bands (the
# municipality search) have a warm tone of their own. The dark theme uses a warm near-black
# with about the luminance of GitHub's #0d1117, so every colour keeps its contrast. Both are
# validated like BACKGROUND: text >= MIN_TEXT_CONTRAST on each, data and the strong end of the
# map ramp >= MIN_GRAPHIC_CONTRAST on the page.
SITE_BACKGROUND = {"light": "#fcfbf9", "dark": "#13110e"}
BAND = {"light": "#efebe2", "dark": "#1f1b16"}

# Validation thresholds (checked by scripts/check_visual_identity.py).
MIN_TEXT_CONTRAST = 4.5  # WCAG 2.x, normal text
MIN_GRAPHIC_CONTRAST = 3.0  # WCAG 2.x, graphical objects (1.4.11)
MIN_DISTINCT_DELTA_E = 15.0  # CAM02-UCS, normal vision and each simulated deficiency


@dataclass(frozen=True)
class Colour:
    role: str
    name_pt: str
    light: str
    dark: str
    kind: str  # "data", "text" or "decoration"
    source: str

    def __getitem__(self, theme: str) -> str:
        return getattr(self, theme)


# --- Data colours: they encode the climate classes, nothing else. ---------------------------
DRY = Colour(
    "dry",
    "seco",
    "#895819",
    "#a36c22",
    "data",
    "IPCC AR6 prec_div: passo 2 de 11 (contínua 26) no claro; contínua 38 no escuro",
)
WET = Colour(
    "wet",
    "úmido",
    "#1a695f",
    "#7cbab5",
    "data",
    "IPCC AR6 prec_div: passo 10 de 11 (contínua 229) no claro; contínua 176 no escuro",
)
HOT = Colour(
    "hot",
    "quente",
    "#67001f",
    "#de8475",
    "data",
    "IPCC AR6 temp_div: passo 11 de 11 (contínua 255) no claro; contínua 186 no escuro",
)
COLD = Colour(
    "cold",
    "frio (geada)",
    "#4393c3",
    "#3379aa",
    "data",
    "IPCC AR6 temp_div: passo 3 de 11 (contínua 51) no claro; contínua 38 no escuro",
)
NEUTRAL = Colour(
    "neutral",
    "neutro (anos normais)",
    "#9a9184",
    "#6e675d",
    "data",
    "cinza quente do projeto, o mais claro (claro) ou escuro (escuro) que ainda tem 3:1",
)
DATA_COLOURS = (DRY, WET, HOT, COLD, NEUTRAL)


# --- Text and decoration. --------------------------------------------------------------------
TEXT = Colour("text", "texto", "#1f1b16", "#f2eee8", "text", "quase preto/branco quente")
TEXT_SECONDARY = Colour(
    "text_secondary", "texto secundário", "#4d473f", "#cec7bc", "text", "eixos e legendas"
)
TEXT_MUTED = Colour(
    "text_muted", "texto discreto", "#6b6359", "#a39b8f", "text", "rodapé, fontes, eixo zero"
)
GRID = Colour(
    "grid", "grade", "#ece9e4", "#222831", "decoration", "decorativa, sem requisito de contraste"
)
TEXT_COLOURS = (TEXT, TEXT_SECONDARY, TEXT_MUTED)
ALL_COLOURS = (*DATA_COLOURS, *TEXT_COLOURS, GRID)

# Pairs that must stay distinguishable in every chart (the others are validated too).
REQUIRED_DISTINCT_PAIRS = (("dry", "neutral"), ("hot", "cold"))

# --- Sequential scale for the choropleth map (production intensity). -------------------------
# Single-hue ramp in the warm-grey family of NEUTRAL: brown means dry and blue-green means wet
# in this identity, so neither can encode intensity. It runs light-to-dark on the light theme
# and dark-to-light on the dark theme, keeping the strong end at maximum contrast with the
# background. Steps are evenly spaced in CAM02-UCS between the endpoints; a lightness-only
# ramp keeps its ordering under every colour-vision deficiency. Validated by
# scripts/check_visual_identity.py: monotonic luminance, extremes >= MIN_TEXT_CONTRAST,
# strong end vs background >= MIN_GRAPHIC_CONTRAST and adjacent steps >= MIN_DISTINCT_DELTA_E
# with normal vision and under each simulated deficiency.
SEQUENTIAL = {
    "light": ("#f2ede3", "#c1bcb2", "#969088", "#6e6961", "#49443d", "#241f19"),
    "dark": ("#211d1a", "#47423e", "#6c6761", "#948e87", "#bfb9b0", "#f0eadf"),
}

# --- Typography. -----------------------------------------------------------------------------
# Three voices of one superfamily, IBM Plex (github.com/IBM/plex, SIL OFL 1.1): serif for the
# titles, sans for the running text, mono for numbers, labels and metadata. Static files from
# IBM's official releases, bundled with the licence (fonts/OFL.txt, the same text for the three
# families). scripts/check_visual_identity.py validates every file: family name, licence,
# REQUIRED_CHARACTERS, a zero without slash or dot, I, l and 1 with different outlines,
# x-height >= MIN_X_HEIGHT_EM and matplotlib picking the right file for each weight.
FONT_DIR = Path(__file__).parent / "fonts"
# Characters the charts and the site print: digits, signs, Portuguese accents, punctuation.
REQUIRED_CHARACTERS = "0123456789%+−–—·×≤°…“”‘’áàâãéêíóôõúüçÁÀÂÃÉÊÍÓÔÕÚÇ"
MIN_X_HEIGHT_EM = 0.5


@dataclass(frozen=True)
class Typeface:
    role: str
    name_pt: str
    family: str
    files: tuple[tuple[int, str], ...]  # (CSS weight, bundled TTF); only the weights in use
    features: tuple[str, ...]  # OpenType features always on
    release: str


TEXT_FACE = Typeface(
    "text",
    "texto corrido e interface",
    "IBM Plex Sans",
    ((400, "IBMPlexSans-Regular.ttf"), (700, "IBMPlexSans-Bold.ttf")),
    (),
    "@ibm/plex-sans@1.1.0 (fonte 3.005)",
)
TITLE_FACE = Typeface(
    "titles",
    "títulos e parágrafo de abertura",
    "IBM Plex Serif",
    ((400, "IBMPlexSerif-Regular.ttf"),),
    (),
    "@ibm/plex-serif@2.0.0 (fonte 3.006)",
)
# Plex Mono's default zero has a dot and its "zero" feature slashes it; ss04 gives the plain
# zero of the Sans and the Serif. A marked zero is what ruled out Atkinson Hyperlegible
# ("2ØØ5" in years and percentages).
NUMBER_FACE = Typeface(
    "numbers",
    "números, rótulos e metadados",
    "IBM Plex Mono",
    ((400, "IBMPlexMono-Regular.ttf"), (600, "IBMPlexMono-SemiBold.ttf")),
    ("ss04",),
    "@ibm/plex-mono@2.5.0 (fonte 2.005)",
)
TYPEFACES = (TEXT_FACE, TITLE_FACE, NUMBER_FACE)
# The main number of a page (the 73% of the Análise) is the one number set in the sans bold:
# heavier than any weight of the mono. Every other number stays in the mono.
DISPLAY_NUMBER = (TEXT_FACE, 700)

# matplotlib charts keep the sans for everything (the README chart).
FONT_FAMILY = TEXT_FACE.family
FONT_FILES = tuple(name for face in TYPEFACES for _, name in face.files)
# Type scale in points for a 10-inch-wide figure shown about 800 px wide.
TYPE_SCALE = {"title": 17, "subtitle": 14, "panel_title": 13, "label": 12, "small": 11}
# Site type scale in rem, (narrow, wide): sizes grow linearly between the viewport widths of
# WEB_VIEWPORT_PX, so a phone and the 1,240 px layout each get their own size.
WEB_VIEWPORT_PX = (360, 1240)
WEB_TYPE_SCALE = {
    "display": (3.5, 6.0),  # the main number
    # Page title. 3.25 rem is the largest size at which the Análise title fits two lines in
    # the eight columns of the 1,240 px layout, with its short words kept together.
    "headline": (2.25, 3.25),
    "brand": (1.25, 1.625),  # site name in the header
    "section": (1.5, 2.0),  # section and figure titles
    "stat": (1.75, 2.5),  # supporting numbers
    "deck": (1.125, 1.3125),  # opening paragraph
    "body": (1.0, 1.0625),  # running text
    "meta": (0.8125, 0.875),  # labels, sources and metadata (mono)
}


def palette(theme: str) -> dict[str, str]:
    """Role -> hex for one theme, including the background."""
    return {"background": BACKGROUND[theme], **{c.role: c[theme] for c in ALL_COLOURS}}


def as_dict() -> dict:
    """Plain, JSON-serialisable description of the identity (e.g. for a Power BI theme)."""
    return {
        "font_family": FONT_FAMILY,
        "typefaces": [
            {
                "role": face.role,
                "name_pt": face.name_pt,
                "family": face.family,
                "weights": [weight for weight, _ in face.files],
                "features": list(face.features),
                "release": face.release,
            }
            for face in TYPEFACES
        ],
        "display_number": {"role": DISPLAY_NUMBER[0].role, "weight": DISPLAY_NUMBER[1]},
        "type_scale_pt": TYPE_SCALE,
        "web_type_scale_rem": {
            "viewport_px": list(WEB_VIEWPORT_PX),
            **{role: list(sizes) for role, sizes in WEB_TYPE_SCALE.items()},
        },
        "background": BACKGROUND,
        "site_background": SITE_BACKGROUND,
        "band": BAND,
        "sequential": {
            "name_pt": "escala sequencial (intensidade no mapa)",
            "light": list(SEQUENTIAL["light"]),
            "dark": list(SEQUENTIAL["dark"]),
            "source": "rampa na família do neutro, passos uniformes em CAM02-UCS",
        },
        "colours": [
            {
                "role": c.role,
                "name_pt": c.name_pt,
                "kind": c.kind,
                "light": c.light,
                "dark": c.dark,
                "source": c.source,
            }
            for c in ALL_COLOURS
        ],
    }


def register_fonts() -> None:
    """Make the bundled fonts available to matplotlib (no system installation needed)."""
    from matplotlib import font_manager

    for name in FONT_FILES:
        font_manager.fontManager.addfont(str(FONT_DIR / name))


def rc_params(theme: str) -> dict:
    """matplotlib style for one theme, derived from the colours and type scale above."""
    p = palette(theme)
    return {
        "font.family": FONT_FAMILY,
        "font.size": TYPE_SCALE["label"],
        "figure.facecolor": p["background"],
        "axes.facecolor": p["background"],
        "savefig.facecolor": p["background"],
        "text.color": p["text"],
        "axes.titlecolor": p["text"],
        "axes.labelcolor": p["text_secondary"],
        "axes.edgecolor": p["text_muted"],
        "axes.linewidth": 0.8,
        "axes.grid": False,
        "grid.color": p["grid"],
        "grid.linewidth": 0.9,
        "xtick.color": p["text_secondary"],
        "ytick.color": p["text_secondary"],
        "xtick.labelsize": TYPE_SCALE["label"],
        "ytick.labelsize": TYPE_SCALE["label"],
        "legend.frameon": False,
        "legend.labelcolor": p["text_secondary"],
        "axes.spines.top": False,
        "axes.spines.right": False,
    }


def apply_style(theme: str) -> dict[str, str]:
    """Register the font, apply the style and return the theme palette."""
    import matplotlib.pyplot as plt

    register_fonts()
    plt.style.use(rc_params(theme))
    return palette(theme)
