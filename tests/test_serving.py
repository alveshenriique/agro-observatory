"""Serving layer: TopoJSON encoder, mesh snapping, file contract and packaging (no database)."""

import json
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest
import shapely
from shapely.geometry import MultiPolygon, Polygon, box

from atlas_da_lavoura.serving import build, contract, export, mesh, package, topojson
from atlas_da_lavoura.serving.warehouse import Table

# --- TopoJSON -------------------------------------------------------------------------------


def grid_coverage() -> list[tuple[int, Polygon | MultiPolygon]]:
    """A 3 x 3 grid of squares, one with an enclave, plus a two-part municipality."""
    cells = []
    for i in range(3):
        for j in range(3):
            cells.append((10 * i + j + 1, box(i, j, i + 1, j + 1)))
    container = box(1, 1, 2, 2)
    enclave = box(1.4, 1.4, 1.6, 1.6)
    cells[4] = (cells[4][0], container.difference(enclave))
    cells.append((99, enclave))
    cells.append((100, MultiPolygon([box(4, 0, 5, 1), box(4, 2, 5, 3)])))
    return cells


def decoded(topology, name="m", quantized=True):
    return topojson.decode(topology, name, quantized=quantized)


def test_topojson_round_trip_keeps_ids_shapes_and_coverage() -> None:
    items = grid_coverage()
    topology = topojson.encode({"m": items}, 1001)
    out = decoded(topology)
    assert [i for i, _ in out] == [i for i, _ in items]
    geometries = np.array([g for _, g in out], dtype=object)
    assert shapely.is_valid(geometries).all()
    assert shapely.coverage_is_valid(geometries[:-1])  # the grid, the enclave and its container
    assert all(topojson.exterior_rings_are_clockwise(g) for g in geometries)
    # Dequantized coordinates come back in degrees, within one grid cell (5 / 1000 wide).
    real = dict(decoded(topology, quantized=False))
    assert real[1].bounds == pytest.approx((0, 0, 1, 1), abs=0.005)
    assert real[99].area == pytest.approx(0.04, rel=0.05)
    assert real[100].area == pytest.approx(2.0, rel=0.01)


def test_topojson_stores_shared_borders_once() -> None:
    topology = topojson.encode({"m": grid_coverage()}, 1001)
    references = [
        i
        for g in topology["objects"]["m"]["geometries"]
        for polygon in (g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]])
        for ring in polygon
        for i in ring
    ]
    assert any(i < 0 for i in references)  # some arcs are traversed backwards by a neighbour
    used = {i if i >= 0 else ~i for i in references}
    assert used == set(range(len(topology["arcs"])))  # no orphan arcs
    assert len(references) > len(topology["arcs"])  # shared arcs are referenced twice


def test_topojson_enclave_shares_its_ring_with_the_container_hole() -> None:
    topology = topojson.encode({"m": grid_coverage()}, 1001)
    geometries = {g["id"]: g for g in topology["objects"]["m"]["geometries"]}
    hole = geometries[12]["arcs"][1]  # the container's hole (the centre cell)
    enclave = geometries[99]["arcs"][0]
    assert [~i for i in hole] == enclave or [~i for i in enclave] == hole


def test_topojson_rejects_a_geometry_that_vanishes_on_the_grid() -> None:
    tiny = [(1, box(0, 0, 100, 100)), (2, box(200, 200, 200.001, 200.001))]
    with pytest.raises(ValueError, match="vanished"):
        topojson.encode({"m": tiny}, 1000)


# --- mesh -----------------------------------------------------------------------------------


def test_snap_coverage_keeps_a_narrow_neck_valid() -> None:
    """A neck narrower than one grid cell: rounding each vertex makes the ring cross itself."""
    dumbbell = shapely.union_all([box(0, 0, 4, 10), box(6, 0, 10, 10), box(4, 4.97, 6, 5.03)])
    below, above = box(4, 0, 6, 4.97), box(4, 5.03, 6, 10)
    items = [(1, dumbbell), (2, below), (3, above)]
    ids = [i for i, _ in items]
    geometries = np.array([g for _, g in items], dtype=object)
    bbox = [float(v) for v in shapely.total_bounds(geometries)]  # 0..10: cells of 0.1

    plain = np.array(
        [g for _, g in decoded(topojson.encode({"m": items}, 101, bbox))], dtype=object
    )
    assert not shapely.is_valid(plain[0])  # the neck collapsed onto itself

    snapped = mesh.snap_coverage(ids, geometries, bbox, 101)
    topology = topojson.encode({"m": list(zip(ids, snapped, strict=True))}, 101, bbox)
    out = np.array([g for _, g in decoded(topology)], dtype=object)
    assert shapely.is_valid(out).all()
    assert shapely.coverage_is_valid(out)
    assert len(out[0].geoms) == 2  # the dumbbell keeps its two halves; the neck has no area


def test_resolve_overlaps_keeps_the_overlap_with_the_smaller_code() -> None:
    a, b = box(0, 0, 1, 1), box(0.99, 0, 2, 1)  # 0.01 x 1 overlap
    geometries, fixes = mesh.resolve_overlaps([10, 20], np.array([a, b], dtype=object))
    assert [f["kept_by"] for f in fixes] == [10] and fixes[0]["removed_from"] == 20
    assert geometries[0].equals(a)
    assert geometries[1].area == pytest.approx(1.0)
    assert shapely.coverage_is_valid(geometries)


def test_resolve_overlaps_fails_on_a_gap() -> None:
    a, b = box(0, 0, 1, 1), box(1.0, 0, 2, 0.999)
    jagged = Polygon([(1, 0), (2, 0), (2, 1), (1, 1), (1.0005, 0.5)])  # leaves a sliver gap
    with pytest.raises(ValueError, match="not a valid coverage"):
        mesh.resolve_overlaps([1, 2, 3], np.array([a, jagged, b.buffer(0)], dtype=object))


# --- contract -------------------------------------------------------------------------------

SERIES = (
    "soybean",
    "corn",
    "coffee_in_husk",
    "coffee_processed",
    "coffee_arabica",
    "coffee_canephora",
)
SPANS = {
    "soybean": (2000, 2003),
    "corn": (2000, 2003),
    "coffee_in_husk": (2000, 2001),
    "coffee_processed": (2002, 2003),
    "coffee_arabica": (2012, 2013),
    "coffee_canephora": (2012, 2013),
}
D = Decimal


def tables() -> dict[str, Table]:
    """Minimal serving views: 2 municipalities in one immediate region of one state."""
    t = {}
    t["serve_series"] = Table(
        [
            "series",
            "crop",
            "sort_order",
            "series_name_pt",
            "production_unit_pt",
            "area_name_pt",
            "first_year",
            "last_year",
            "real_value_first_year",
            "climate_crop",
        ],
        [
            (
                s,
                s,
                k,
                s,
                "t",
                "área",
                SPANS[s][0],
                SPANS[s][1],
                max(SPANS[s][0], 2001),
                "soybean" if s == "soybean" else None,
            )
            for k, s in enumerate(SERIES)
        ],
    )
    t["serve_parameters"] = Table(
        [
            "deflation_base_year",
            "real_value_first_year",
            "coffee_unit_break_year",
            "coffee_breakdown_first_year",
            "climate_normal_start_year",
            "climate_normal_end_year",
        ],
        [(2025, 2001, 2002, 2012, 1991, 2020)],
    )
    t["serve_municipalities"] = Table(
        [
            "municipality_id",
            "municipality_name",
            "state_id",
            "state_abbreviation",
            "state_name",
            "region_id",
            "region_name",
            "intermediate_region_id",
            "intermediate_region_name",
            "immediate_region_id",
            "immediate_region_name",
            "first_pam_year",
            "representative_lat",
            "representative_lon",
        ],
        [
            (
                5100102,
                "A",
                51,
                "MT",
                "Mato Grosso",
                5,
                "Centro-Oeste",
                5101,
                "I",
                510001,
                "R",
                2000,
                D("-12.5"),
                D("-55.7"),
            ),
            (
                5100201,
                "B",
                51,
                "MT",
                "Mato Grosso",
                5,
                "Centro-Oeste",
                5101,
                "I",
                510001,
                "R",
                None,
                None,
                None,
            ),
        ],
    )
    production_columns = [
        "municipality_id",
        "state_id",
        "immediate_region_id",
        "series",
        "year",
        "production_t",
        "harvested_area_ha",
        "planted_or_bearing_area_ha",
        "production_value_real_thousand_brl",
        "rank_country",
        "rank_state",
        "rank_immediate_region",
    ]
    rows = []
    for s in SERIES:
        for year in range(SPANS[s][0], SPANS[s][1] + 1):
            real = D(10) if year >= max(SPANS[s][0], 2001) else None
            rows.append((5100102, 51, 510001, s, year, D(100), D(50), D(55), real, 1, 1, 1))
    t["serve_municipality_production"] = Table(production_columns, rows)
    territory_columns = [
        "territory_level",
        "territory_id",
        "territory_name",
        "series",
        "year",
        "production_t",
        "harvested_area_ha",
        "planted_or_bearing_area_ha",
        "production_value_real_thousand_brl",
        "municipalities_with_data",
        "producing_municipalities",
    ]
    trows = []
    for level, tid, name in (
        ("country", 1, "Brasil"),
        ("macro_region", 5, "Centro-Oeste"),
        ("state", 51, "Mato Grosso"),
        ("immediate_region", 510001, "R"),
    ):
        for r in rows:
            trows.append((level, tid, name, r[3], r[4], r[5], r[6], r[7], r[8], 1, 1))
    t["serve_territory_production"] = Table(territory_columns, trows)
    climate_columns = [
        "territory_level",
        "territory_id",
        "territory_name",
        "crop",
        "harvest_year",
        "primary_window",
        "municipalities",
        "is_normal_available",
        "is_trend_available",
        "is_territory_standardized",
        "water_balance_z",
        "precipitation_pct_of_normal",
        "hot_days_z",
        "hot_days_anomaly_days",
        "heat_degree_days_z",
        "longest_dry_spell_z",
        "frost_tmin_min_c",
        "frost_area_share",
        "is_water_deficit",
        "is_heat_stress",
        "is_frost",
        "yield_kg_ha",
        "trend_yield_kg_ha",
        "trend_method",
        "yield_anomaly",
    ]
    t["serve_climate_territory_year"] = Table(
        climate_columns,
        [
            (
                level,
                tid,
                "x",
                "soybean",
                2003,
                "critical",
                1,
                True,
                True,
                True,
                D("-1.2"),
                D("60.0"),
                D("0.5"),
                D("2.0"),
                D("0.4"),
                D("0.1"),
                None,
                None,
                True,
                False,
                None,
                D(2900),
                D(3100),
                "log_linear_ols",
                D("-0.0645"),
            )
            for level, tid in (("state", 51), ("immediate_region", 510001))
        ],
    )
    summary_columns = [
        "territory_level",
        "territory_id",
        "territory_name",
        "crop",
        "trend_method",
        "n_years",
        "first_year",
        "last_year",
        "water_deficit_years",
        "water_deficit_share",
        "mean_anomaly_water_deficit_years",
        "mean_anomaly_no_water_deficit_years",
        "water_deficit_hit_rate",
        "negative_anomaly_share_all_years",
        "corr_water_balance_yield",
        "heat_stress_years",
        "mean_anomaly_heat_stress_years",
        "heat_stress_hit_rate",
        "frost_years",
        "mean_anomaly_frost_years",
        "frost_hit_rate",
    ]
    t["serve_climate_territory_summary"] = Table(
        summary_columns,
        [
            (
                "state",
                51,
                "x",
                "soybean",
                "log_linear_ols",
                20,
                1991,
                2010,
                4,
                D("0.2"),
                D("-0.1"),
                D("0.02"),
                D("0.75"),
                D("0.45"),
                D("0.4"),
                2,
                D("-0.05"),
                D("0.5"),
                0,
                None,
                None,
            )
        ],
    )
    t["serve_analysis_headline"] = Table(
        [
            "crop",
            "state_years",
            "water_deficit_state_years",
            "first_year",
            "last_year",
            "mean_anomaly_water_deficit_years",
            "mean_anomaly_other_years",
            "below_trend_share_water_deficit_years",
            "below_trend_share_all_years",
            "regions_with_positive_correlation",
            "regions_with_correlation",
        ],
        [("soybean", 1, 1, 2003, 2003, D("-0.0645"), None, D("1.0"), D("1.0"), 1, 1)],
    )
    t["serve_growth_decomposition"] = Table(
        [
            "series",
            "territory_level",
            "territory_id",
            "territory_name",
            "start_anchor",
            "end_anchor",
            "start_period",
            "end_period",
            "start_production_t",
            "end_production_t",
            "start_harvested_area_ha",
            "end_harvested_area_ha",
            "start_yield_kg_ha",
            "end_yield_kg_ha",
            "start_share_of_national_production",
            "is_low_base",
            "ln_production_growth",
            "ln_area_effect",
            "ln_yield_effect",
            "area_share_of_growth",
            "yield_share_of_growth",
        ],
        [
            (
                "soybean",
                "country",
                1,
                "Brasil",
                2001,
                2002,
                "2000–2002",
                "2001–2003",
                100,
                120,
                50,
                55,
                D(2000),
                D(2182),
                D(1),
                False,
                D("0.1823"),
                D("0.0953"),
                D("0.0870"),
                D("0.5228"),
                D("0.4772"),
            )
        ],
    )
    t["serve_concentration"] = Table(
        [
            "series",
            "year",
            "producing_municipalities",
            "national_production_t",
            "municipalities_for_50pct",
            "municipalities_for_80pct",
            "share_of_producers_for_50pct",
            "hhi",
        ],
        [
            (s, y, 1, 100, 1, 1, D(1), D(10000))
            for s in SERIES
            for y in range(SPANS[s][0], SPANS[s][1] + 1)
        ],
    )
    t["serve_coffee_mg_biennial"] = Table(
        [
            "series",
            "year",
            "production_unit",
            "production_t",
            "harvested_area_ha",
            "yield_kg_ha",
            "production_change_vs_previous_year",
            "production_centered_trend_t",
            "production_ratio_to_trend",
            "yield_centered_trend_kg_ha",
            "yield_ratio_to_trend",
            "cycle_phase",
            "yield_cycle_phase",
        ],
        [("coffee_arabica", 2012, "t", 100, 50, D(2000), None, None, None, None, None, None, None)],
    )
    t["serve_soybean_frontier_shares"] = Table(
        [
            "territory_level",
            "territory_id",
            "territory_name",
            "year",
            "production_t",
            "share_of_national_production",
        ],
        [("state", 51, "Mato Grosso", 2003, 100, D(1))],
    )
    t["serve_soybean_frontier_centroid"] = Table(
        ["year", "centroid_lat", "centroid_lon", "production_t", "producing_municipalities"],
        [(2003, D("-12.5"), D("-55.7"), 100, 1)],
    )
    t["serve_soybean_frontier_thresholds"] = Table(
        [
            "territory_id",
            "territory_name",
            "threshold",
            "first_year_reached",
            "first_year_sustained",
            "max_share",
        ],
        [(51, "Mato Grosso", D("0.01"), 2000, 2000, D(1))],
    )
    t["serve_validation_sidra_summary"] = Table(
        ["territory_level", "variable", "status", "cells", "first_year", "last_year"],
        [("country", "production_t", "match", 24, 2000, 2003)],
    )
    t["serve_validation_sidra_scope"] = Table(
        ["category", "sort_order", "description_pt", "cells"],
        [("compared", 1, "valor publicado", 24), ("coffee_breakdown_before_2012", 2, "café", 8)],
    )
    t["serve_validation_sidra_discrepancies"] = Table(
        [
            "territory_level",
            "territory_id",
            "territory_name",
            "series",
            "year",
            "variable",
            "official_value",
            "our_value",
            "difference",
            "relative_difference",
            "status",
            "reason",
        ],
        [],
    )
    t["serve_validation_conab"] = Table(
        [
            "state_abbreviation",
            "harvest_year",
            "conab_planted_area_ha",
            "pam_planted_area_ha",
            "planted_area_relative_difference",
            "conab_production_t",
            "pam_production_t",
            "production_relative_difference",
            "is_compared",
            "is_beyond_tolerance",
        ],
        [("MT", 2003, 60, 55, D("-0.0833"), 110, 100, D("-0.0909"), False, False)],
    )
    return t


def bundle_files() -> dict[str, dict]:
    ctx = build.Context("2026.11.07", "2026-11-07T12:00:00Z", "postgres", True)
    return build.Bundle(tables(), ctx).data_files(None)


def test_bundle_files_match_their_schemas_and_rules() -> None:
    files = bundle_files()
    assert {"catalog.json", "municipalities.json", "analysis.json", "method.json"} <= set(files)
    assert "places/region/510001.json" in files and "places/state/MT.json" in files
    assert len([p for p in files if p.startswith("explore/")]) == len(SERIES) * len(build.MEASURES)
    assert contract.check_all(files) == []


def test_no_data_is_null_and_the_real_value_has_its_own_years() -> None:
    files = bundle_files()
    soybean = files["explore/soybean/production_t.json"]
    assert soybean["values"] == [[100, 100, 100, 100], [None, None, None, None]]  # B has no data
    region = files["places/region/510001.json"]
    block = region["municipalities"][0]["series"]["soybean"]
    assert block["real_value"]["years"] == [2001, 2002, 2003]
    assert files["explore/soybean/production_value_real_thousand_brl.json"]["years"] == [
        2001,
        2002,
        2003,
    ]


def test_rules_reject_a_coffee_series_across_the_break() -> None:
    files = bundle_files()
    files["explore/coffee_in_husk/production_t.json"]["years"] = [2000, 2001, 2002]
    for row in files["explore/coffee_in_husk/production_t.json"]["values"]:
        row.append(None)
    for key in ("country_total", "municipalities_with_data"):
        files["explore/coffee_in_husk/production_t.json"][key].append(None)
    assert any("coffee in husk reaches 2002" in e for e in contract.check_all(files))


def test_rules_reject_climate_fields_at_the_municipal_level() -> None:
    files = bundle_files()
    files["places/region/510001.json"]["municipalities"][0]["yield_anomaly"] = -0.1
    errors = contract.check_all(files)
    assert errors and all("places/region/510001.json" in e for e in errors)


def test_rules_reject_the_raw_coffee_total() -> None:
    files = bundle_files()
    files["analysis.json"]["coffee_mg_biennial"]["production_unit"] = ["coffee_total"]
    assert any("coffee_total" in e for e in contract.check_rules(files))


def test_method_publishes_the_compared_cell_count_with_its_definition() -> None:
    validation = bundle_files()["method.json"]["validation"]
    assert validation["sidra_definition_pt"] == build.SIDRA_COMPARED_CELL_DEFINITION_PT
    scope = validation["sidra_scope"]
    assert dict(zip(scope["category"], scope["cells"], strict=True)) == {
        "compared": 24,
        "coffee_breakdown_before_2012": 8,
    }


def test_rules_reject_a_summary_that_disagrees_with_the_scope() -> None:
    files = bundle_files()
    files["method.json"]["validation"]["sidra_scope"]["cells"][0] = 25
    assert any(
        "compared cells" in e for e in contract.check_file("method.json", files["method.json"])
    )


@pytest.mark.parametrize("doc", ["docs/VALIDACAO.md", "docs/CONTRATO_DE_DADOS.md"])
def test_docs_repeat_the_compared_cell_definition_verbatim(doc) -> None:
    root = Path(__file__).resolve().parents[1]
    assert build.SIDRA_COMPARED_CELL_DEFINITION_PT in (root / doc).read_text(encoding="utf-8")


def test_columnar_tables_must_have_equal_lengths() -> None:
    files = bundle_files()
    files["analysis.json"]["concentration"]["hhi"].pop()
    assert any(
        "different lengths" in e
        for e in contract.check_file("analysis.json", files["analysis.json"])
    )


def test_json_values_reject_unrounded_floats() -> None:
    assert build.json_value(Decimal("4260"), "x") == 4260
    assert build.json_value(Decimal("-0.0899"), "x") == -0.0899
    with pytest.raises(build.UnroundedValueError):
        build.json_value(0.1 + 0.2, "view.column")


# --- export and package ---------------------------------------------------------------------


def run_results(tmp_path, select, target="prod"):
    path = tmp_path / "run_results.json"
    path.write_text(
        json.dumps(
            {
                "metadata": {"dbt_version": "1.12.5", "invocation_id": "x", "generated_at": "t"},
                "args": {"which": "test", "target": target, "select": select},
                "results": [
                    {"unique_id": "test.atlas_da_lavoura.a.1", "status": "pass"},
                    {"unique_id": "test.atlas_da_lavoura.b.2", "status": "warn"},
                    {"unique_id": "model.atlas_da_lavoura.c", "status": "success"},
                ],
            }
        )
    )
    return path


def test_dbt_tests_summary_only_for_a_full_run_on_the_same_warehouse(tmp_path) -> None:
    summary = export.dbt_tests_summary(run_results(tmp_path, []), "bigquery")
    assert (summary["total"], summary["pass"], summary["warn"], summary["warnings"]) == (
        2,
        1,
        1,
        ["b"],
    )
    assert export.dbt_tests_summary(run_results(tmp_path, ["serve"]), "bigquery") is None
    assert export.dbt_tests_summary(run_results(tmp_path, [], target=None), "bigquery") is None
    assert export.dbt_tests_summary(tmp_path / "missing.json", "postgres") is None


def exported_folder(tmp_path, sample=False, warehouse="bigquery"):
    folder = tmp_path / "2026.11.07"
    (folder / "geo").mkdir(parents=True)
    data = b'{"a":1}'
    (folder / "catalog.json").write_bytes(data)
    manifest = {
        "meta": {"data_version": "2026.11.07", "generated_at": "2026-11-07T12:00:00Z"},
        "warehouse": warehouse,
        "sample": sample,
        "git": {"commit": "abc", "dirty": False},
        "files": [
            {
                "path": "catalog.json",
                "schema": "catalog",
                "schema_version": 1,
                "bytes": 7,
                "gzip_bytes": 7,
                "sha256": package.hashlib.sha256(data).hexdigest(),
            }
        ],
        "checks": [{"name": "c", "status": "ok", "detail": "d"}],
    }
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return folder


def test_package_is_reproducible_and_writes_the_pointer(tmp_path) -> None:
    folder = exported_folder(tmp_path)
    pointer = tmp_path / "data-release.json"
    for out in ("a", "b"):
        package.main([str(folder), "--out", str(tmp_path / out), "--pointer", str(pointer)])
    a = (tmp_path / "a" / "site-data-2026.11.07.tar.gz").read_bytes()
    assert a == (tmp_path / "b" / "site-data-2026.11.07.tar.gz").read_bytes()
    written = json.loads(pointer.read_text())
    assert written["release_tag"] == "data-v2026.11.07"
    assert written["sha256"] == package.hashlib.sha256(a).hexdigest()


@pytest.mark.parametrize(("sample", "warehouse"), [(True, "bigquery"), (False, "postgres")])
def test_package_refuses_the_sample_and_non_production_exports(tmp_path, sample, warehouse) -> None:
    folder = exported_folder(tmp_path, sample=sample, warehouse=warehouse)
    with pytest.raises(SystemExit, match="cannot package"):
        package.main(
            [str(folder), "--out", str(tmp_path / "out"), "--pointer", str(tmp_path / "p.json")]
        )


def test_package_detects_a_changed_file(tmp_path) -> None:
    folder = exported_folder(tmp_path)
    (folder / "catalog.json").write_bytes(b'{"a":2}')
    with pytest.raises(SystemExit, match="sha256"):
        package.main(
            [str(folder), "--out", str(tmp_path / "out"), "--pointer", str(tmp_path / "p.json")]
        )
