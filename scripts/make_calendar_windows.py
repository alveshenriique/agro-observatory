"""Generate dbt/seeds/crop_calendar_windows.csv (crop × state × window × month × year_offset).

Soybean windows are derived from the CONAB calendar transcription in
dbt/seeds/conab_soybean_calendar.csv:
- critical: the main planting months (the "plantio" bars, without the "plantio/colheita"
  overlap) shifted by two months, which is roughly flowering to grain filling (R1-R6);
- season: every month from the first planting month to the last harvest month.
`year_offset` says which calendar year a month belongs to relative to the harvest year
(the PAM year): -1 for months before the turn of the year when the cycle crosses it.

Arabica coffee in Minas Gerais uses fixed windows (see README, "Clima x produção").

Usage: uv run python scripts/make_calendar_windows.py
The dbt test assert_calendar_windows_match_conab_rule re-derives the soybean windows in SQL,
so hand edits to the output that break the rule fail the build.
"""

import csv
from pathlib import Path

CONAB_PATH = Path("dbt/seeds/conab_soybean_calendar.csv")
OUTPUT_PATH = Path("dbt/seeds/crop_calendar_windows.csv")
CRITICAL_SHIFT_MONTHS = 2

COFFEE_WINDOWS = {
    ("coffee_arabica", "MG"): {
        "flowering": [(9, -1), (10, -1), (11, -1)],
        "filling": [(12, -1), (1, 0), (2, 0), (3, 0)],
        "frost": [(6, -1), (7, -1), (8, -1)],
    }
}


def cyclic_months(start: int, end: int) -> list[int]:
    """Months from start to end inclusive, wrapping past December."""
    count = (end - start) % 12 + 1
    return [((start - 1 + i) % 12) + 1 for i in range(count)]


def year_offset(month: int, planting_start: int, harvest_end: int) -> int:
    crosses_year = planting_start > harvest_end
    return -1 if crosses_year and month >= planting_start else 0


def soybean_windows(row: dict[str, str]) -> dict[str, list[tuple[int, int]]]:
    planting_start = int(row["planting_start_month"])
    planting_end = int(row["planting_end_month"])
    harvest_end = int(row["harvest_end_month"])

    critical = [
        ((month - 1 + CRITICAL_SHIFT_MONTHS) % 12) + 1
        for month in cyclic_months(planting_start, planting_end)
    ]
    season = cyclic_months(planting_start, harvest_end)
    return {
        "critical": [(m, year_offset(m, planting_start, harvest_end)) for m in critical],
        "season": [(m, year_offset(m, planting_start, harvest_end)) for m in season],
    }


def main() -> None:
    rows = []
    with CONAB_PATH.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            for window, months in soybean_windows(row).items():
                for month, offset in months:
                    rows.append(("soybean", row["state_abbreviation"], window, month, offset))
    for (crop, state), windows in COFFEE_WINDOWS.items():
        for window, months in windows.items():
            for month, offset in months:
                rows.append((crop, state, window, month, offset))

    rows.sort(key=lambda r: (r[0], r[1], r[2], r[4], r[3]))
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["crop", "state_abbreviation", "window_name", "month", "year_offset"])
        writer.writerows(rows)
    print(f"{OUTPUT_PATH}: {len(rows)} rows")


if __name__ == "__main__":
    main()
