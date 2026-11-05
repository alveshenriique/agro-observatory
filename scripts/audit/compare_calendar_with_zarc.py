"""Audit: compare the CONAB soybean planting windows (dbt/seeds/conab_soybean_calendar.csv)
with the sowing windows of MAPA's ZARC risk table, aggregated by state.

ZARC gives, per municipality × soil × cultivar cycle, 36 ten-day periods (dec1..dec36) with
a risk level (20, 30, 40 = recommended at 20/30/40% risk; 0 = not recommended). For each
state, this script computes the share of ZARC rows that recommend sowing in each month
(a month counts for a row when any of its three periods has a non-zero level) and prints it
next to the CONAB planting months, for the largest producing states.

Usage: uv run python scripts/audit/compare_calendar_with_zarc.py <zarc_csv> [--states MT PR ...]
"""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

MONTH_NAMES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def cyclic_months(start: int, end: int) -> set[int]:
    return {((start - 1 + i) % 12) + 1 for i in range((end - start) % 12 + 1)}


def read_conab(path: Path) -> dict[str, dict[str, set[int]]]:
    windows = {}
    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            planting = cyclic_months(
                int(row["planting_start_month"]), int(row["planting_end_month"])
            )
            overlap = set()
            if row["overlap_start_month"]:
                overlap = cyclic_months(
                    int(row["overlap_start_month"]), int(row["overlap_end_month"])
                )
            windows[row["state_abbreviation"]] = {"planting": planting, "overlap": overlap}
    return windows


def zarc_month_shares(path: Path, states: set[str]) -> dict[str, list[float]]:
    rows_by_state: dict[str, int] = defaultdict(int)
    month_hits: dict[str, list[int]] = defaultdict(lambda: [0] * 12)
    with path.open(newline="", encoding="utf-8-sig") as file:
        for row in csv.DictReader(file, delimiter=";"):
            if row["Nome_cultura"] != "Soja" or row["UF"] not in states:
                continue
            rows_by_state[row["UF"]] += 1
            for month in range(12):
                periods = (
                    row[f"dec{3 * month + 1}"],
                    row[f"dec{3 * month + 2}"],
                    row[f"dec{3 * month + 3}"],
                )
                if any(p not in ("", "0") for p in periods):
                    month_hits[row["UF"]][month] += 1
    return {uf: [hits / rows_by_state[uf] for hits in month_hits[uf]] for uf in rows_by_state}


def month_list(months: set[int]) -> str:
    return ",".join(MONTH_NAMES[m - 1] for m in sorted(months)) or "-"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("zarc_csv", type=Path)
    parser.add_argument("--states", nargs="+", default=["MT", "PR", "GO", "RS", "MS", "MG"])
    parser.add_argument("--conab", type=Path, default=Path("dbt/seeds/conab_soybean_calendar.csv"))
    args = parser.parse_args()

    conab = read_conab(args.conab)
    shares = zarc_month_shares(args.zarc_csv, set(args.states))

    print("Share of ZARC soybean rows (municipality x soil x cycle) recommending sowing per month;")
    print("CONAB planting months marked with * (plantio) and + (plantio/colheita overlap).\n")
    header = "UF  " + "".join(f"{m:>7}" for m in MONTH_NAMES)
    print(header)
    for uf in args.states:
        cells = []
        for month in range(1, 13):
            mark = (
                "*"
                if month in conab[uf]["planting"]
                else ("+" if month in conab[uf]["overlap"] else " ")
            )
            cells.append(f"{100 * shares[uf][month - 1]:5.0f}%{mark}")
        print(f"{uf:<4}" + "".join(f"{c:>7}" for c in cells))
    print("\nZARC months with >= 50% of rows vs CONAB planting months:")
    for uf in args.states:
        zarc_months = {m for m in range(1, 13) if shares[uf][m - 1] >= 0.5}
        conab_months = conab[uf]["planting"]
        print(
            f"  {uf}: ZARC>=50% {month_list(zarc_months)} | CONAB {month_list(conab_months)} | "
            f"only ZARC {month_list(zarc_months - conab_months)} | "
            f"only CONAB {month_list(conab_months - zarc_months)}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
