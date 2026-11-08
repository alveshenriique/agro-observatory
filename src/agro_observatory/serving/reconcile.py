"""Reconciliation of the published files with the marts (independent of the serving views).

The serving views are tested by dbt; this module checks the files themselves against the
marts, with its own queries, after they are written:
- every explore matrix: per year, the sum of the municipal values equals the fact table's sum
  (exactly for tonnes and hectares; within 0.5 per municipality for the real value, which is
  rounded per municipality), the count of values equals the fact rows (the rest is null, "no
  data") and, for production, the count of zeros equals the fact's zeros;
- the Brazil file equals the fact's totals; the states and the immediate regions add up to
  Brazil; each immediate region equals the sum of its municipalities;
- the main finding, recomputed in Python from the association mart;
- the climate rows of the state and region files equal the association mart's rows;
- the mesh: decoded, a valid coverage with exactly the municipalities of the index (a subset
  in the CI sample), exterior rings clockwise, the state files partitioning the national one.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

import numpy as np
import shapely

from agro_observatory.serving import topojson
from agro_observatory.serving.build import MEASURES, QUANTITIES, REAL_VALUE
from agro_observatory.serving.warehouse import Warehouse


def queries(wh: Warehouse) -> dict[str, str]:
    fct = wh.relation("marts", "fct_crop_production")
    association = wh.relation("marts", "agg_climate_yield_association")
    summary = wh.relation("marts", "agg_climate_yield_association_summary")
    return {
        "fact_totals": (
            "select crop, year, count(*) as rows_with_data,"
            " sum(case when production_t = 0 then 1 else 0 end) as zero_rows, "
            + ", ".join(
                f"sum({m}) as {m}, sum(case when {m} is not null then 1 else 0 end) as {m}__rows"
                for m in MEASURES
            )
            + f" from {fct} group by crop, year"
        ),
        "headline_rows": (
            "select yield_anomaly_pct, is_water_deficit"
            f" from {association} where crop = 'soybean' and territory_level = 'state'"
            " and is_normal_available and is_trend_available"
        ),
        "region_correlations": (
            f"select corr_water_balance_yield from {summary} where crop = 'soybean'"
            " and territory_level = 'immediate_region' and corr_water_balance_yield is not null"
        ),
        "climate_rows": (
            "select territory_level, crop, count(*) as n"
            f" from {association} where territory_level in ('state', 'immediate_region')"
            " and crop in ('soybean', 'coffee_arabica') group by territory_level, crop"
        ),
    }


def _series(crop: str, year: int, break_year: int) -> str:
    if crop == "coffee_total":
        return "coffee_in_husk" if year < break_year else "coffee_processed"
    return crop


def _num(value) -> float:
    return float(value) if isinstance(value, (Decimal, float, int)) else 0.0


class Checks:
    def __init__(self) -> None:
        self.results: list[dict] = []

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.results.append({"name": name, "status": "ok" if ok else "fail", "detail": detail})

    @property
    def failed(self) -> list[dict]:
        return [r for r in self.results if r["status"] == "fail"]


def reconcile(wh: Warehouse, files: dict[str, dict], sample: bool) -> list[dict]:
    q = {name: wh.query(sql).records() for name, sql in queries(wh).items()}
    catalog = files["catalog.json"]
    break_year = catalog["parameters"]["coffee_unit_break_year"]
    checks = Checks()

    # Fact totals by published series and year; a measure without any value is None ("no
    # data", e.g. planted area before 1988), not zero.
    fact: dict[tuple[str, int], dict] = defaultdict(lambda: defaultdict(float))
    for r in q["fact_totals"]:
        key = (_series(r["crop"], r["year"], break_year), r["year"])
        for c in ("rows_with_data", "zero_rows", *(f"{m}__rows" for m in MEASURES), *MEASURES):
            fact[key][c] += _num(r[c])
    for f in fact.values():
        for m in MEASURES:
            if not f[f"{m}__rows"]:
                f[m] = None

    # Explore matrices.
    problems = []
    n_municipalities = catalog["municipality_count"]
    for path, payload in files.items():
        if payload["meta"]["schema"] != "explore":
            continue
        measure, series = payload["measure"], payload["series"]
        for j, year in enumerate(payload["years"]):
            column = [row[j] for row in payload["values"]]
            present = [v for v in column if v is not None]
            f = fact.get((series, year))
            if f is None:
                if present:
                    problems.append(f"{path} {year}: values without fact rows")
                continue
            expected_rows = f[f"{measure}__rows"]
            if len(present) != expected_rows:
                problems.append(
                    f"{path} {year}: {len(present)} values, {expected_rows:.0f} fact rows"
                )
            tolerance = 0.5 * len(present) + 1e-6 if measure == REAL_VALUE else 0
            if present and abs(sum(present) - f[measure]) > tolerance:
                problems.append(f"{path} {year}: sum {sum(present)} != fact {f[measure]}")
            if measure == "production_t" and sum(1 for v in present if v == 0) != f["zero_rows"]:
                problems.append(f"{path} {year}: zeros differ from the fact")
            if len(column) != n_municipalities:
                problems.append(
                    f"{path} {year}: {len(column)} rows for {n_municipalities} municipalities"
                )
    checks.add(
        "explore matrices equal the fact table",
        not problems,
        "; ".join(problems[:5]) or "sums, counts, zeros and nulls per series, measure and year",
    )

    # Places: Brazil equals the fact; states and regions add up; regions equal their municipalities.
    country = files["places/country.json"]["series"]
    problems = []
    for series, block in country.items():
        for j, year in enumerate(block["years"]):
            f = fact.get((series, year))
            for c in QUANTITIES:
                expected = f[c] if f else None
                if (block[c][j] is None) != (expected is None) or (
                    expected is not None and block[c][j] != expected
                ):
                    problems.append(f"country {series} {year} {c}: {block[c][j]} != {expected}")
            if f and f[f"{REAL_VALUE}__rows"]:
                value = (
                    block["real_value"][REAL_VALUE][block["real_value"]["years"].index(year)]
                    if year in block["real_value"]["years"]
                    else None
                )
                if value is None or abs(value - f[REAL_VALUE]) > 0.5 + 1e-6:
                    problems.append(
                        f"country {series} {year} real value: {value} != {f[REAL_VALUE]}"
                    )

    def add_up(prefix: str) -> dict[tuple[str, int, str], int]:
        totals: dict[tuple[str, int, str], int] = defaultdict(int)
        for path, payload in files.items():
            if path.startswith(prefix):
                for series, block in payload["series"].items():
                    for j, year in enumerate(block["years"]):
                        for c in QUANTITIES:
                            totals[(series, year, c)] += block[c][j] or 0
        return totals

    expected_country = {
        (s, y, c): b[c][j] or 0
        for s, b in country.items()
        for j, y in enumerate(b["years"])
        for c in QUANTITIES
    }
    for prefix in ("places/state/", "places/region/", "places/macro_region/"):
        totals = add_up(prefix)
        diff = [k for k, v in expected_country.items() if totals.get(k, 0) != v]
        if diff:
            problems.append(f"{prefix}* do not add up to Brazil: {diff[:3]}")
    for path, payload in files.items():
        if not path.startswith("places/region/"):
            continue
        for series, block in payload["series"].items():
            for c in QUANTITIES:
                sums = [0] * len(block["years"])
                for m in payload["municipalities"]:
                    for j, v in enumerate(m["series"][series][c]):
                        sums[j] += v or 0
                if [v or 0 for v in block[c]] != sums:
                    problems.append(f"{path} {series} {c}: region != sum of municipalities")
                    break
    checks.add(
        "territorial files add up",
        not problems,
        "; ".join(problems[:5])
        or "Brazil = fact; states, macro-regions, regions = Brazil; region = its municipalities",
    )

    # Main finding, recomputed from the association mart.
    rows = q["headline_rows"]
    headline = files["analysis.json"]["headline"]
    problems = []
    if rows:
        anomalies = np.array([float(r["yield_anomaly_pct"]) for r in rows])
        deficit = np.array([bool(r["is_water_deficit"]) for r in rows])
        expected = {
            "state_years": len(rows),
            "water_deficit_state_years": int(deficit.sum()),
            "mean_anomaly_water_deficit_years": anomalies[deficit].mean()
            if deficit.any()
            else None,
            "mean_anomaly_other_years": anomalies[~deficit].mean() if (~deficit).any() else None,
            "below_trend_share_water_deficit_years": (anomalies[deficit] < 0).mean()
            if deficit.any()
            else None,
            "below_trend_share_all_years": (anomalies < 0).mean(),
        }
        for key, value in expected.items():
            got = headline[key]
            if value is None or got is None:
                if value != got:
                    problems.append(f"{key}: {got} != {value}")
            elif abs(got - value) > 5e-5:
                problems.append(f"{key}: {got} != {value:.6f}")
    correlations = [float(r["corr_water_balance_yield"]) for r in q["region_correlations"]]
    if headline["regions_with_correlation"] != len(correlations) or (
        (headline["regions_with_positive_correlation"] or 0) != sum(c > 0 for c in correlations)
    ):
        problems.append("regions with positive correlation differ")
    checks.add(
        "main finding matches the association mart",
        not problems,
        "; ".join(problems)
        or f"{headline['state_years']} state-years, {len(correlations)} regions",
    )

    # Climate rows of the place files.
    published: dict[tuple[str, str], int] = defaultdict(int)
    for payload in files.values():
        if payload["meta"]["schema"] == "place":
            level = payload["territory"]["level"]
            for crop, climate in payload.get("climate", {}).items():
                published[(level, crop)] += len(climate["years"]["harvest_year"])
    expected_climate = {(r["territory_level"], r["crop"]): int(r["n"]) for r in q["climate_rows"]}
    checks.add(
        "climate rows equal the association mart",
        dict(published) == expected_climate,
        f"published {dict(sorted(published.items()))}, "
        f"mart {dict(sorted(expected_climate.items()))}",
    )

    # Mesh.
    index_ids = files["municipalities.json"]["municipalities"]["municipality_id"]
    national = files["geo/municipalities.topo.json"]
    decoded = topojson.decode(national, "municipalities", quantized=True)
    ids = [i for i, _ in decoded]
    geometries = np.array([g for _, g in decoded], dtype=object)
    ids_ok = set(ids) <= set(index_ids) if sample else ids == index_ids
    valid = bool(shapely.is_valid(geometries).all())
    coverage = bool(shapely.coverage_is_valid(geometries))
    clockwise = all(topojson.exterior_rings_are_clockwise(g) for g in geometries)
    state_ids: list[int] = []
    states_ok = True
    for path, payload in files.items():
        if path.startswith("geo/state/"):
            part = topojson.decode(payload, "municipalities", quantized=True)
            state_ids.extend(i for i, _ in part)
            g = np.array([x for _, x in part], dtype=object)
            states_ok &= bool(shapely.is_valid(g).all()) and bool(shapely.coverage_is_valid(g))
    states_ok &= sorted(state_ids) == sorted(ids)
    outlines = topojson.decode(files["geo/states.topo.json"], "states", quantized=True)
    outline_geoms = np.array([g for _, g in outlines], dtype=object)
    outlines_ok = bool(shapely.is_valid(outline_geoms).all()) and bool(
        shapely.coverage_is_valid(outline_geoms)
    )
    checks.add(
        "mesh decodes to a valid coverage of the index",
        ids_ok and valid and coverage and clockwise and states_ok and outlines_ok,
        f"{len(ids)} municipalities ({'subset of' if sample else 'equal to'} the index: {ids_ok}),"
        f" valid {valid}, coverage {coverage}, clockwise {clockwise},"
        f" state files partition it and are valid {states_ok}, state outlines valid {outlines_ok}",
    )
    return checks.results
