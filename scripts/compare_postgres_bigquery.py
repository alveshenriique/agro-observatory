"""Cross-validate the BigQuery production warehouse against the local Postgres (read-only).

For every model and seed table: row counts on both sides, then a full comparison by grain.
Text, integers, booleans and dates must be identical; numbers (NUMERIC, FLOAT64) may differ
only by floating-point rounding: |a - b| <= REL * max(|a|, |b|) or |a - b| <= ABS, which covers
the last digits of doubles and values near zero (anomalies computed as ratio - 1). Postgres
`real` columns are read as double precision, the exact 32-bit value that BigQuery stores.
Also prints the samples asked for in phase 10b: Sorriso-MT soybean 2025, Brazil totals by crop
and year, and the climate x yield association summary for soybean by state.
Usage (from the repository root): uv run python scripts/compare_postgres_bigquery.py
Exit code 1 if anything differs beyond the tolerance.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import psycopg
from dotenv import find_dotenv, load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agro_observatory import bigquery_ops as ops  # noqa: E402
from agro_observatory.load_raw import conninfo_from_env  # noqa: E402

REL, ABS = 1e-9, 1e-9
GRAINS = {
    "intermediate.int_bcb__ipca_annual": ["year"],
    "intermediate.int_climate__producing_municipalities": ["municipality_id", "crop"],
    "intermediate.int_climate__window_indicators": [
        "municipality_id", "crop", "window_name", "harvest_year"
    ],
    "intermediate.int_climate__window_normals": ["municipality_id", "crop", "window_name"],
    "intermediate.int_pam__crop_year": ["municipality_id", "crop", "year"],
    "intermediate.int_yield__territory_trend": [
        "territory_level", "territory_id", "crop", "harvest_year"
    ],
    "marts.agg_climate_yield_association": [
        "territory_level", "territory_id", "crop", "harvest_year"
    ],
    "marts.agg_climate_yield_association_summary": ["territory_level", "territory_id", "crop"],
    "marts.agg_coffee_mg_biennial": ["series", "year"],
    "marts.agg_production_concentration": ["crop", "year"],
    "marts.agg_production_growth_decomposition": [
        "crop", "territory_id", "start_anchor", "end_anchor"
    ],
    "marts.agg_production_share_by_territory": [
        "crop", "year", "territory_level", "territory_id"
    ],
    "marts.agg_territory_share_thresholds": [
        "crop", "territory_level", "territory_id", "threshold"
    ],
    "marts.dim_crop": ["crop"],
    "marts.dim_municipality": ["municipality_id"],
    "marts.dim_year": ["year"],
    "marts.fct_crop_climate": ["municipality_id", "crop", "harvest_year"],
    "marts.fct_crop_production": ["municipality_id", "crop", "year"],
}  # fmt: skip
SEEDS = (
    "conab_soybean_calendar",
    "conab_soybean_series",
    "crop_calendar_windows",
    "crops",
    "known_climate_events",
    "sidra_known_discrepancies",
    "sidra_official_aggregates",
)


def is_number(value) -> bool:
    return isinstance(value, (float, Decimal)) and not isinstance(value, bool)


def close(a, b) -> bool:
    a, b = float(a), float(b)
    diff = abs(a - b)
    return diff <= ABS or diff <= REL * max(abs(a), abs(b))


def postgres_rows(conn, fq_table: str) -> tuple[list[str], list[tuple]]:
    schema, table = fq_table.split(".")
    columns = conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns"
        " WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
        (schema, table),
    ).fetchall()
    select = ", ".join(
        f'"{c}"::double precision AS "{c}"' if t == "real" else f'"{c}"' for c, t in columns
    )
    cur = conn.execute(f'SELECT {select} FROM "{schema}"."{table}"')
    return [d.name for d in cur.description], cur.fetchall()


def bigquery_rows(client, fq_table: str) -> tuple[list[str], list[tuple]]:
    table = client.get_table(f"{client.project}.{fq_table}")
    if table.table_type == "VIEW":  # list_rows reads only tables; a view needs a query
        rows = client.query(f"select * from `{table.full_table_id.replace(':', '.')}`").result(
            page_size=50_000
        )
    else:
        rows = client.list_rows(table, page_size=50_000)
    names = [field.name for field in table.schema]
    return names, [tuple(row.values()) for row in rows]


def compare_table(conn, client, fq_table: str, grain: list[str]) -> dict:
    pg_names, pg = postgres_rows(conn, fq_table)
    bq_names, bq = bigquery_rows(client, fq_table)
    result = {"table": fq_table, "pg_rows": len(pg), "bq_rows": len(bq), "issues": []}
    if sorted(pg_names) != sorted(bq_names):
        result["issues"].append(f"columns differ: {set(pg_names) ^ set(bq_names)}")
        return result
    index = [bq_names.index(c) for c in pg_names]
    bq = [tuple(r[i] for i in index) for r in bq]
    key = [pg_names.index(c) for c in grain]
    pg_map = {tuple(r[i] for i in key): r for r in pg}
    bq_map = {tuple(r[i] for i in key): r for r in bq}
    if pg_map.keys() != bq_map.keys():
        result["issues"].append(
            f"keys differ: {len(pg_map.keys() - bq_map.keys())} only on Postgres, "
            f"{len(bq_map.keys() - pg_map.keys())} only on BigQuery"
        )
        return result
    max_rel, mismatches = 0.0, {}
    for k, pg_row in pg_map.items():
        for name, a, b in zip(pg_names, pg_row, bq_map[k], strict=True):
            if a == b or (a is None and b is None):
                continue
            if a is not None and b is not None and is_number(a) and is_number(b):
                m = max(abs(float(a)), abs(float(b)))
                if m > 1e-6:
                    max_rel = max(max_rel, abs(float(a) - float(b)) / m)
                if close(a, b):
                    continue
            mismatches[name] = mismatches.get(name, 0) + 1
    result["max_rel"] = max_rel
    if mismatches:
        result["issues"].append(f"values beyond tolerance: {mismatches}")
    return result


def print_samples(conn, client) -> None:
    def side_by_side(title: str, sql: str, pg_cast: str = "") -> None:
        print(f"\n== {title}")
        pg_sql = sql.replace("{real}", pg_cast)
        bq_sql = sql.replace("{real}", "")
        for row in sorted(conn.execute(pg_sql).fetchall()):
            print("  postgres:", row)
        for row in sorted(tuple(r.values()) for r in client.query(bq_sql).result()):
            print("  bigquery:", row)

    sorriso = "municipality_id = 5107925 and crop = 'soybean'"
    side_by_side(
        "Sorriso-MT (5107925), soybean 2025: fct_crop_production",
        "select production_t, harvested_area_ha, yield_kg_ha, production_value_real_thousand_brl"
        f" from marts.fct_crop_production where {sorriso} and year = 2025",
    )
    side_by_side(
        "Sorriso-MT soybean 2025: fct_crop_climate, critical window",
        "select critical_precipitation_mm{real}, critical_water_balance_z, critical_hot_days,"
        f" critical_heat_degree_days from marts.fct_crop_climate where {sorriso}"
        " and harvest_year = 2025",
        pg_cast="::double precision",
    )

    totals = (
        "select crop, year, sum(production_t), sum(harvested_area_ha),"
        " sum(production_value_real_thousand_brl) from marts.fct_crop_production group by 1, 2"
    )
    pg = {(r[0], r[1]): r[2:] for r in conn.execute(totals).fetchall()}
    bq = {(r[0], r[1]): tuple(r.values())[2:] for r in client.query(totals).result()}
    same_quantities = sum(pg[k][:2] == bq[k][:2] for k in pg)
    real_close = sum(
        (pg[k][2] is None and bq[k][2] is None)
        or (pg[k][2] is not None and bq[k][2] is not None and close(pg[k][2], bq[k][2]))
        for k in pg
    )
    print("\n== Brazil totals by crop and year (fct_crop_production)")
    print(f"  crop-years: postgres {len(pg)}, bigquery {len(bq)}")
    print(f"  production and harvested area identical: {same_quantities} of {len(pg)}")
    print(f"  real production value within tolerance: {real_close} of {len(pg)}")
    for k in [("soybean", 2025), ("corn", 2025), ("coffee_total", 2025), ("soybean", 1975)]:
        print(f"  {k}: postgres {tuple(pg[k][:2])} | bigquery {tuple(bq[k][:2])}")

    side_by_side(
        "Association summary, soybean by state (RS, PR, MT)",
        "select territory_name, n_years, corr_water_balance_yield, water_deficit_years,"
        " mean_anomaly_water_deficit_years, water_deficit_hit_rate"
        " from marts.agg_climate_yield_association_summary where crop = 'soybean'"
        " and territory_level = 'state' and territory_name in ('RS', 'PR', 'MT')",
    )


def main() -> int:
    load_dotenv(find_dotenv(usecwd=True))
    client = ops.client()
    failed = 0
    with psycopg.connect(conninfo_from_env()) as conn:
        conn.execute("SET statement_timeout = '300s'")
        print(f"{'table':52s} {'postgres':>10s} {'bigquery':>10s}  max rel   result")
        for fq_table, grain in GRAINS.items():
            r = compare_table(conn, client, fq_table, grain)
            ok = not r["issues"] and r["pg_rows"] == r["bq_rows"]
            failed += not ok
            rel = f"{r.get('max_rel', 0):.1e}"
            print(f"{fq_table:52s} {r['pg_rows']:>10,} {r['bq_rows']:>10,}  {rel:>8s}  "
                  f"{'OK' if ok else 'DIFF ' + '; '.join(r['issues'])}")  # fmt: skip
        for seed in SEEDS:
            pg = conn.execute(f'SELECT count(*) FROM seeds."{seed}"').fetchone()[0]
            bq = client.get_table(f"{client.project}.seeds.{seed}").num_rows
            failed += pg != bq
            result = "OK" if pg == bq else "DIFF"
            print(f"{'seeds.' + seed:52s} {pg:>10,} {bq:>10,}  {'':>8s}  {result}")
        print_samples(conn, client)
    print(f"\n{'all tables agree' if not failed else f'{failed} table(s) differ'}"
          f" (tolerance: relative {REL:g} or absolute {ABS:g})")  # fmt: skip
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
