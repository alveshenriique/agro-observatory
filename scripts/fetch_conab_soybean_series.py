"""Download CONAB's historical grain series (Portal de Informações) and save the soybean rows
by state as the seed dbt/seeds/conab_soybean_series.csv.

CONAB estimates planted area, production and yield by state per crop year ("2023/24"); the
PAM year is the harvest (calendar) year, so "2023/24" maps to PAM 2024. The methodologies
differ (CONAB surveys the season as it happens; IBGE's PAM is the municipal census after the
harvest), so the dbt test assert_soybean_matches_conab only warns beyond a tolerance.

Usage: uv run python scripts/fetch_conab_soybean_series.py
"""

import csv
import sys
from pathlib import Path

import httpx

SOURCE_URL = "https://portaldeinformacoes.conab.gov.br/downloads/arquivos/SerieHistoricaGraos.txt"
OUTPUT_PATH = Path("dbt/seeds/conab_soybean_series.csv")
PRODUCT = "SOJA"


def main() -> int:
    response = httpx.get(SOURCE_URL, timeout=300, follow_redirects=True)
    response.raise_for_status()
    lines = response.text.splitlines()
    reader = csv.DictReader(lines, delimiter=";")
    rows = []
    for row in reader:
        if row["produto"].strip() != PRODUCT or row["dsc_safra_previsao"].strip() != "UNICA":
            continue
        crop_year = row["ano_agricola"].strip()
        harvest_year = int(crop_year[:4]) + 1
        rows.append(
            {
                "state_abbreviation": row["uf"].strip(),
                "crop_year": crop_year,
                "harvest_year": harvest_year,
                "planted_area_ha": round(float(row["area_plantada_mil_ha"]) * 1000),
                "production_t": round(float(row["producao_mil_t"]) * 1000),
                "yield_kg_ha": round(float(row["produtividade_mil_ha_mil_t"]) * 1000),
            }
        )
    rows.sort(key=lambda r: (r["state_abbreviation"], r["harvest_year"]))
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"{OUTPUT_PATH}: {len(rows)} rows, {rows[0]['crop_year']} to {rows[-1]['crop_year']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
