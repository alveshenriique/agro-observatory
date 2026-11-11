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
BACKGROUND = {"light": "#ffffff", "dark": "#0d1117"}

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
# IBM Plex Sans 3.005 (github.com/IBM/plex, SIL OFL 1.1), static files bundled with the licence.
FONT_FAMILY = "IBM Plex Sans"
FONT_DIR = Path(__file__).parent / "fonts"
FONT_FILES = ("IBMPlexSans-Regular.ttf", "IBMPlexSans-Bold.ttf")
# Type scale in points for a 10-inch-wide figure shown about 800 px wide.
TYPE_SCALE = {"title": 17, "subtitle": 14, "panel_title": 13, "label": 12, "small": 11}


def palette(theme: str) -> dict[str, str]:
    """Role -> hex for one theme, including the background."""
    return {"background": BACKGROUND[theme], **{c.role: c[theme] for c in ALL_COLOURS}}


def as_dict() -> dict:
    """Plain, JSON-serialisable description of the identity (e.g. for a Power BI theme)."""
    return {
        "font_family": FONT_FAMILY,
        "type_scale_pt": TYPE_SCALE,
        "background": BACKGROUND,
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
    """Make the bundled font available to matplotlib (no system installation needed)."""
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
