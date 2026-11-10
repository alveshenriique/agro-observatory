"""Render the README headline chart from the marts: soybean yield in drought years.

Left panel: yield anomaly (yield / technological trend - 1) of soybean in one state (Rio
Grande do Sul by default) by harvest year, with the water-deficit years (z <= -1 in the
critical window, flowering and grain filling) in the project's dry brown and the other years
in its warm neutral grey.
Right panel: the same anomaly for every state-year with a normal and a trend, split by the
deficit class, with the mean of each group. The means and the subtitle numbers (share of
deficit years below the trend, share of all years below it) come from serve.serve_analysis_headline,
the model that also feeds the website, so the README and the site show the same numbers.

Colours, font and style come from the visual identity (src/atlas_da_lavoura/viz/identity.py,
validated by scripts/check_visual_identity.py). Reads marts.agg_climate_yield_association and
serve.serve_analysis_headline in the Postgres configured by .env and writes two PNGs with solid
backgrounds (light: #ffffff, dark: #0d1117, the GitHub page colours), so the image also reads
well outside GitHub. The README picks one per theme with <picture>.
Sized to stay legible when shown about 800 px wide. Usage:
    uv run python scripts/make_readme_chart.py [--state RS] [--out docs/img]
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import matplotlib
import numpy as np
import psycopg
from dotenv import find_dotenv, load_dotenv

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FixedLocator, FuncFormatter  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from atlas_da_lavoura.load_raw import conninfo_from_env  # noqa: E402
from atlas_da_lavoura.viz import identity as vi  # noqa: E402

STATE_NAMES = {"RS": "Rio Grande do Sul", "PR": "Paraná", "MT": "Mato Grosso"}

TITLE = "Anos de seca na floração coincidem com quedas no rendimento da soja"
FOOTER = "Associação, não causalidade. Fontes: IBGE (PAM), BR-DWGD (Xavier et al., 2022), Conab."

SERIES_SQL = """
select harvest_year, yield_anomaly_pct, is_water_deficit
from marts.agg_climate_yield_association
where crop = 'soybean' and territory_level = 'state' and territory_name = %s
  and is_normal_available and is_trend_available
order by harvest_year
"""

# Fixed order: the jitter of each dot depends on its position in the result, so an unordered
# query would move the dots whenever the table is rebuilt.
STACKED_SQL = """
select harvest_year, yield_anomaly_pct, is_water_deficit
from marts.agg_climate_yield_association
where crop = 'soybean' and territory_level = 'state'
  and is_normal_available and is_trend_available
order by territory_id, harvest_year
"""


HEADLINE_SQL = """
select state_years, mean_anomaly_water_deficit_years, mean_anomaly_other_years,
    below_trend_share_water_deficit_years, below_trend_share_all_years
from serve.serve_analysis_headline
"""


def fetch(state: str) -> tuple[list[tuple], list[tuple], dict[str, float]]:
    load_dotenv(find_dotenv(usecwd=True))
    with psycopg.connect(conninfo_from_env()) as conn, conn.cursor() as cur:
        cur.execute("set statement_timeout = '60s'")
        series = cur.execute(SERIES_SQL, (state,)).fetchall()
        stacked = cur.execute(STACKED_SQL).fetchall()
        row = cur.execute(HEADLINE_SQL).fetchone()
    if not series:
        raise SystemExit(f"no soybean series for state {state}")
    if row is None or row[0] != len(stacked):
        raise SystemExit("serve.serve_analysis_headline is missing or out of date: run dbt build")
    headline = {
        "mean_def": 100 * float(row[1]),
        "mean_other": 100 * float(row[2]),
        "hit": 100 * float(row[3]),
        "base": 100 * float(row[4]),
    }
    return series, stacked, headline


def signed(value: float, suffix: str = "") -> str:
    """+12 / 0 / −9 with a real minus sign."""
    n = round(value)
    text = f"{n:+d}" if n else "0"
    return text.replace("-", "−") + suffix


def text_runs(fig, x: float, y: float, runs: list[tuple[str, dict]]) -> None:
    """Draw consecutive text runs with different styles on one baseline (figure coords)."""
    renderer = fig.canvas.get_renderer()
    for text, style in runs:
        t = fig.text(x, y, text, ha="left", va="baseline", **style)
        x = fig.transFigure.inverted().transform(t.get_window_extent(renderer).p1)[0]


def render(state: str, series, stacked, headline: dict[str, float], theme: str, out: Path) -> None:
    # Only the drought years carry colour (dry); the other years are the neutral, in both panels.
    c = vi.apply_style(theme)
    size = vi.TYPE_SCALE
    years = np.array([r[0] for r in series])
    anomaly = 100 * np.array([float(r[1]) for r in series])
    deficit = np.array([bool(r[2]) for r in series])

    all_years = np.array([r[0] for r in stacked])
    all_anom = 100 * np.array([float(r[1]) for r in stacked])
    all_def = np.array([bool(r[2]) for r in stacked])
    mean_def, mean_other = headline["mean_def"], headline["mean_other"]
    hit, base = headline["hit"], headline["base"]

    fig, (ax, ax2) = plt.subplots(
        1,
        2,
        figsize=(10, 5.8),
        dpi=200,
        sharey=True,
        gridspec_kw={"width_ratios": [2.85, 1.4], "wspace": 0.05},
    )
    for a in (ax, ax2):
        a.tick_params(length=0, pad=6)
        a.yaxis.grid(True)
        a.set_axisbelow(True)
        a.axhline(0, color=c["text_muted"], linewidth=1, zorder=1)
    ax2.spines["left"].set_visible(False)
    ax2.tick_params(labelleft=False)

    # Shared y range: just past the lowest and highest values of both panels.
    ymin = math.floor(min(anomaly.min(), all_anom.min()) - 4)
    ymax = math.ceil(max(anomaly.max(), all_anom.max()) + 4)
    ax.set_ylim(ymin, ymax)
    ax.yaxis.set_major_locator(FixedLocator([v for v in range(-80, 81, 20) if ymin < v < ymax]))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: signed(v)))
    ax.set_ylabel("rendimento em relação à tendência (%)", fontsize=size["label"], labelpad=8)

    # Left: one bar per harvest year.
    colors = np.where(deficit, c["dry"], c["neutral"])
    ax.bar(years, anomaly, width=0.72, color=colors, linewidth=0, zorder=2)
    ax.set_xlim(years.min() - 0.8, years.max() + 0.8)
    ax.set_xticks([y for y in years if y % 5 == 0])
    ax.set_title(
        f"{STATE_NAMES.get(state, state)}, {years.min()}–{years.max()}",
        loc="left",
        fontsize=size["panel_title"],
        pad=10,
    )
    # Label the three worst drought years beside the bar tip (left side near the right edge).
    worst = sorted(np.where(deficit)[0], key=lambda i: anomaly[i])[:3]
    for i in worst:
        right_side = years[i] + 5 <= years.max()
        ax.annotate(
            f"{years[i]}: {signed(anomaly[i], '%')}",
            (years[i] + (0.45 if right_side else -0.45), anomaly[i]),
            textcoords="offset points",
            xytext=(3 if right_side else -3, 0),
            ha="left" if right_side else "right",
            va="center",
            fontsize=size["small"],
            color=c["text_secondary"],
        )

    # Right: every state-year, by class, with the group mean.
    rng = np.random.default_rng(42)
    # Opaque dots keep the validated colours exact; a thin ring in the background colour
    # separates overlapping dots.
    for x, mask, color, mean in (
        (0, all_def, c["dry"], mean_def),
        (1, ~all_def, c["neutral"], mean_other),
    ):
        jitter = rng.uniform(-0.24, 0.24, mask.sum())
        ax2.scatter(
            x + jitter,
            all_anom[mask],
            s=16,
            color=color,
            edgecolors=c["background"],
            linewidths=0.4,
            zorder=2,
        )
        ax2.hlines(mean, x - 0.34, x + 0.34, color=c["text"], linewidth=2.5, zorder=3)
    ax2.set_xlim(-0.6, 1.6)
    ax2.set_xticks(
        [0, 1],
        [
            f"anos de seca,\nmédia {signed(mean_def, '%')}",
            f"demais anos,\nmédia {signed(mean_other, '%')}",
        ],
    )
    ax2.set_title(
        f"Todas as UFs, {all_years.min()}–{all_years.max()}",
        loc="left",
        fontsize=size["panel_title"],
        pad=10,
    )

    # Headline: conclusion as title, the key number in bold in the subtitle, then the legend.
    left = 0.012
    fig.text(
        left,
        0.965,
        TITLE,
        fontsize=size["title"],
        fontweight="bold",
        color=c["text"],
        ha="left",
        va="top",
    )
    text_runs(
        fig,
        left,
        0.862,
        [
            (f"{round(hit)}%", {"fontsize": 16, "fontweight": "bold", "color": c["text"]}),
            (
                f" dos anos de seca ficaram abaixo da tendência, contra {round(base)}% dos "
                "anos em geral",
                {"fontsize": size["subtitle"], "color": c["text_secondary"]},
            ),
        ],
    )
    handles = [
        plt.Rectangle((0, 0), 1, 1, color=c["dry"]),
        plt.Rectangle((0, 0), 1, 1, color=c["neutral"]),
    ]
    fig.legend(
        handles,
        ["seca na floração e enchimento", "demais anos"],
        loc="upper left",
        bbox_to_anchor=(left - 0.004, 0.845),
        ncol=2,
        fontsize=size["label"],
        handlelength=1.1,
        columnspacing=1.6,
    )
    fig.text(
        left, 0.018, FOOTER, fontsize=size["small"], color=c["text_muted"], ha="left", va="bottom"
    )

    fig.subplots_adjust(left=0.085, right=0.99, top=0.7, bottom=0.15)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)
    print(f"wrote {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--state", default="RS", help="state abbreviation (default: RS)")
    parser.add_argument("--out", default="docs/img", help="output folder (default: docs/img)")
    args = parser.parse_args()
    series, stacked, headline = fetch(args.state)
    for theme in vi.THEMES:
        out = Path(args.out) / f"soybean_yield_anomaly_{args.state.lower()}_{theme}.png"
        render(args.state, series, stacked, headline, theme, out)


if __name__ == "__main__":
    main()
