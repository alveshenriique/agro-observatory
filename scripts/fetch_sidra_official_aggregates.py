"""Download the aggregates IBGE itself publishes for SIDRA table 5457 (PAM) at the Brazil (N1)
and state (N3) levels, for the crops and variables the project uses, and save them as the seed
dbt/seeds/sidra_official_aggregates.csv.

The project's marts are sums over municipalities; the dbt tests
assert_production_matches_sidra_* compare those sums with these official aggregates, which
is the only check that the pipeline reproduces what IBGE publishes.

Usage: uv run python scripts/fetch_sidra_official_aggregates.py
"""

import csv
import sys
from pathlib import Path

import httpx

OUTPUT_PATH = Path("dbt/seeds/sidra_official_aggregates.csv")
SIDRA_URL = "https://apisidra.ibge.gov.br/values/t/5457/{level}/all/v/214,216,112,8331/p/all/c782/{products}"
LEVELS = {"n1": "country", "n3": "state"}
PRODUCTS = {
    "40124": "soybean",
    "40122": "corn",
    "40139": "coffee_total",
    "40140": "coffee_arabica",
    "40141": "coffee_canephora",
}
VARIABLES = {
    "214": "production_t",
    "216": "harvested_area_ha",
    "112": "yield_kg_ha",
    "8331": "planted_area_ha",
}
# IBGE special symbols: "-" is an absolute zero, the others mean "no number".
SPECIAL = {"-": "0", "...": "", "..": "", "X": "", "0": "0"}


def main() -> int:
    rows = []
    with httpx.Client(timeout=300) as client:
        for level, level_name in LEVELS.items():
            url = SIDRA_URL.format(level=level, products=",".join(PRODUCTS))
            payload = client.get(url).json()
            for row in payload[1:]:
                value = row["V"]
                rows.append(
                    {
                        "territory_level": level_name,
                        "territory_id": row["D1C"],
                        "territory_name": row["D1N"],
                        "crop": PRODUCTS[row["D4C"]],
                        "year": row["D3C"],
                        "variable": VARIABLES[row["D2C"]],
                        "official_value": SPECIAL.get(value, value),
                        "raw_value": value,
                    }
                )
    rows.sort(
        key=lambda r: (r["territory_level"], r["territory_id"], r["crop"], r["year"], r["variable"])
    )
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"{OUTPUT_PATH}: {len(rows)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
