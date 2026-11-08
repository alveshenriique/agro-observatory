"""Payloads of the published files, built from the serving views (one read per view).

Every file starts with a `meta` block (schema, schema version, data version, generation time,
sources). Tables are columnar: an object of arrays of the same length. Municipal matrices and
the index follow the canonical order: ascending IBGE municipality code. In every file `null`
means "no data" and 0 is a zero published by the source.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from agro_observatory.serving.sources import SOURCES
from agro_observatory.serving.warehouse import Table

SCHEMA_VERSIONS = {
    "catalog": 1,
    "municipalities": 1,
    "explore": 1,
    "place": 1,
    "analysis": 1,
    "method": 1,
    "topology": 1,
    "manifest": 1,
}

# Serving views read by the exporter, each with one query.
VIEWS = (
    "serve_series",
    "serve_parameters",
    "serve_municipalities",
    "serve_municipality_production",
    "serve_territory_production",
    "serve_climate_territory_year",
    "serve_climate_territory_summary",
    "serve_analysis_headline",
    "serve_growth_decomposition",
    "serve_concentration",
    "serve_coffee_mg_biennial",
    "serve_soybean_frontier_shares",
    "serve_soybean_frontier_centroid",
    "serve_soybean_frontier_thresholds",
    "serve_validation_sidra_summary",
    "serve_validation_sidra_discrepancies",
    "serve_validation_sidra_scope",
    "serve_validation_conab",
)

QUANTITIES = ("production_t", "harvested_area_ha", "planted_or_bearing_area_ha")
REAL_VALUE = "production_value_real_thousand_brl"
MEASURES = (*QUANTITIES, REAL_VALUE)
MEASURE_LABELS = {
    "production_t": ("Produção", "conforme a série (production_unit_pt)"),
    "harvested_area_ha": ("Área colhida", "ha"),
    "planted_or_bearing_area_ha": ("Área plantada (café: área em produção)", "ha"),
    REAL_VALUE: ("Valor da produção, em reais do ano-base", "mil R$"),
}
RANKS = ("rank_immediate_region", "rank_state", "rank_country")
CLIMATE_CROPS = ("soybean", "coffee_arabica")
WINDOW_LABELS = {
    "critical": "na floração e enchimento",
    "filling": "no enchimento dos grãos",
    "flowering": "na floração",
}

FILE_PATTERNS = {
    "catalog": "catalog.json",
    "municipalities": "municipalities.json",
    "analysis": "analysis.json",
    "method": "method.json",
    "explore": "explore/{series}/{measure}.json",
    "country": "places/country.json",
    "macro_region": "places/macro_region/{id}.json",
    "state": "places/state/{abbreviation}.json",
    "immediate_region": "places/region/{id}.json",
    "geo_municipalities": "geo/municipalities.topo.json",
    "geo_states": "geo/states.topo.json",
    "geo_state": "geo/state/{abbreviation}.topo.json",
    "manifest": "manifest.json",
}


# The one definition of the count of the IBGE validation, published in method.json (the site
# and the release notes read it there) and repeated verbatim in docs/VALIDACAO.md and
# docs/CONTRATO_DE_DADOS.md (tests/test_serving.py checks it). No numbers in it: the counts
# come from serve_validation_sidra_scope and change when the data does.
SIDRA_COMPARED_CELL_DEFINITION_PT = (
    "Célula comparada: um valor que o IBGE publica para o Brasil ou para uma UF na tabela 5457 "
    "do SIDRA, para uma cultura (soja, milho, café total, café arábica ou café canéfora), um ano "
    "e uma variável (produção, área colhida, área plantada ou rendimento), confrontado com a "
    'soma dos municípios do projeto. As combinações sem valor publicado ("...") não entram: '
    "arábica e canéfora antes de 2012, área plantada antes de 1988 e UFs em anos sem valor "
    "publicado."
)


class UnroundedValueError(TypeError):
    """A serving view returned a float: every published decimal must be rounded in dbt."""


def json_value(value, where: str):
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, float):
        raise UnroundedValueError(f"{where}: float {value!r}; round it in the serving view")
    raise TypeError(f"{where}: unsupported value {value!r} ({type(value).__name__})")


@dataclass
class Rows:
    """A view as converted rows (tuples) with a column index."""

    columns: list[str]
    rows: list[tuple]

    @classmethod
    def of(cls, name: str, table: Table) -> Rows:
        rows = [
            tuple(json_value(v, f"{name}.{c}") for c, v in zip(table.columns, row, strict=True))
            for row in table.rows
        ]
        return cls(list(table.columns), rows)

    def col(self, name: str) -> int:
        return self.columns.index(name)

    def records(self) -> list[dict]:
        return [dict(zip(self.columns, r, strict=True)) for r in self.rows]


def columnar(records: list[dict], columns: list[str]) -> dict[str, list]:
    return {c: [r[c] for r in records] for c in columns}


@dataclass
class Context:
    data_version: str
    generated_at: str
    warehouse: str
    sample: bool

    def meta(self, schema: str, sources: list[str]) -> dict:
        return {
            "schema": schema,
            "schema_version": SCHEMA_VERSIONS[schema],
            "data_version": self.data_version,
            "generated_at": self.generated_at,
            "sources": sources,
        }


class Bundle:
    """Builds every data file (not the mesh) from the converted views."""

    def __init__(self, tables: dict[str, Table], ctx: Context):
        self.ctx = ctx
        self.v = {name: Rows.of(name, tables[name]) for name in VIEWS}
        self.series = sorted(self.v["serve_series"].records(), key=lambda r: r["sort_order"])
        self.series_by_key = {s["series"]: s for s in self.series}
        self.parameters = self.v["serve_parameters"].records()[0]
        self.municipalities = sorted(
            self.v["serve_municipalities"].records(), key=lambda r: r["municipality_id"]
        )
        self.municipality_ids = [m["municipality_id"] for m in self.municipalities]
        self._production = self._index_production()

    # --- helpers --------------------------------------------------------------------------

    def _index_production(self) -> dict[str, dict[int, dict[int, tuple]]]:
        rows = self.v["serve_municipality_production"]
        s, m, y = rows.col("series"), rows.col("municipality_id"), rows.col("year")
        out: dict[str, dict[int, dict[int, tuple]]] = defaultdict(lambda: defaultdict(dict))
        for row in rows.rows:
            out[row[s]][row[m]][row[y]] = row
        return out

    def years(self, series: str, measure: str | None = None) -> list[int]:
        meta = self.series_by_key[series]
        first = meta["real_value_first_year"] if measure == REAL_VALUE else meta["first_year"]
        return list(range(first, meta["last_year"] + 1))

    def _block(self, by_year: dict[int, dict], series: str, columns: tuple[str, ...]) -> dict:
        years = self.years(series)
        real_years = self.years(series, REAL_VALUE)
        block = {"years": years}
        for column in columns:
            block[column] = [by_year[y][column] if y in by_year else None for y in years]
        block["real_value"] = {
            "years": real_years,
            REAL_VALUE: [by_year[y][REAL_VALUE] if y in by_year else None for y in real_years],
        }
        return block

    def _climate_labels(self) -> dict:
        rows = self.v["serve_climate_territory_year"].records()
        windows = {r["crop"]: r["primary_window"] for r in rows}
        labels = {}
        for crop, window in sorted(windows.items()):
            where = WINDOW_LABELS.get(window, f"na janela {window}")
            labels[crop] = {
                "primary_window": window,
                "is_water_deficit": f"seca {where}",
                "is_heat_stress": f"calor extremo {where}",
                "is_frost": "geada no inverno" if crop == "coffee_arabica" else None,
            }
        return labels

    # --- files ------------------------------------------------------------------------------

    def catalog(self) -> dict:
        p = self.parameters
        climate_years = [
            r["harvest_year"] for r in self.v["serve_climate_territory_year"].records()
        ]
        conab_years = [r["harvest_year"] for r in self.v["serve_validation_conab"].records()]

        def period(values: list[int]) -> str | None:
            return f"{min(values)}–{max(values)}" if values else None

        periods = {
            "ibge_pam": period(
                [s["first_year"] for s in self.series] + [s["last_year"] for s in self.series]
            ),
            "bcb_ipca": f"{p['real_value_first_year']}–{p['deflation_base_year']}",
            "brdwgd": period(climate_years),
            "conab_calendar": "edição 2022",
            "conab_series": period(conab_years),
            "ibge_localities": "divisão territorial atual",
            "ibge_mesh": "malha atual",
        }
        sources = {
            key: {**value, "reference_period_pt": periods.get(key)}
            for key, value in SOURCES.items()
        }
        series_columns = [
            "series",
            "series_name_pt",
            "production_unit_pt",
            "area_name_pt",
            "first_year",
            "last_year",
            "real_value_first_year",
            "climate_crop",
        ]
        return {
            "meta": self.ctx.meta("catalog", sorted(SOURCES)),
            "project": {
                "name": "Agro Observatory",
                "repository": "https://github.com/alveshenriique/agro-observatory",
            },
            "warehouse": self.ctx.warehouse,
            "sample": self.ctx.sample,
            "municipality_count": len(self.municipalities),
            "null_means": "sem dado",
            "parameters": p,
            "series": columnar(self.series, series_columns),
            "measures": {
                "measure": list(MEASURES),
                "label_pt": [MEASURE_LABELS[m][0] for m in MEASURES],
                "unit_pt": [MEASURE_LABELS[m][1] for m in MEASURES],
            },
            "climate_labels": self._climate_labels(),
            "sources": sources,
            "files": FILE_PATTERNS,
        }

    def municipalities_index(self) -> dict:
        ms = self.municipalities
        states = {}
        regions = {}
        macro = {}
        for m in ms:
            states[m["state_id"]] = {
                "state_id": m["state_id"],
                "state_abbreviation": m["state_abbreviation"],
                "state_name": m["state_name"],
                "region_id": m["region_id"],
            }
            regions[m["immediate_region_id"]] = {
                "immediate_region_id": m["immediate_region_id"],
                "immediate_region_name": m["immediate_region_name"],
                "state_id": m["state_id"],
                "intermediate_region_id": m["intermediate_region_id"],
                "intermediate_region_name": m["intermediate_region_name"],
            }
            macro[m["region_id"]] = {"region_id": m["region_id"], "region_name": m["region_name"]}
        return {
            "meta": self.ctx.meta("municipalities", ["ibge_localities", "ibge_pam"]),
            "municipalities": columnar(
                ms,
                [
                    "municipality_id",
                    "municipality_name",
                    "state_id",
                    "state_abbreviation",
                    "immediate_region_id",
                    "first_pam_year",
                ],
            ),
            "states": columnar(
                [states[k] for k in sorted(states)],
                ["state_id", "state_abbreviation", "state_name", "region_id"],
            ),
            "immediate_regions": columnar(
                [regions[k] for k in sorted(regions)],
                [
                    "immediate_region_id",
                    "immediate_region_name",
                    "state_id",
                    "intermediate_region_id",
                    "intermediate_region_name",
                ],
            ),
            "macro_regions": columnar(
                [macro[k] for k in sorted(macro)], ["region_id", "region_name"]
            ),
        }

    def explore(self) -> dict[str, dict]:
        rows = self.v["serve_municipality_production"]
        territory = self._territories()
        out = {}
        for s in self.series:
            key = s["series"]
            by_municipality = self._production.get(key, {})
            country = territory.get(("country", 1), {}).get(key, {})
            for measure in MEASURES:
                c = rows.col(measure)
                years = self.years(key, measure)
                values = [
                    [
                        by_municipality[mid][y][c]
                        if mid in by_municipality and y in by_municipality[mid]
                        else None
                        for y in years
                    ]
                    for mid in self.municipality_ids
                ]
                sources = ["ibge_pam", "bcb_ipca"] if measure == REAL_VALUE else ["ibge_pam"]
                out[f"explore/{key}/{measure}.json"] = {
                    "meta": self.ctx.meta("explore", sources),
                    "series": key,
                    "measure": measure,
                    "unit_pt": s["production_unit_pt"]
                    if measure == "production_t"
                    else MEASURE_LABELS[measure][1],
                    "municipality_count": len(self.municipality_ids),
                    "years": years,
                    "values": values,
                    "country_total": [country[y][measure] if y in country else None for y in years],
                    "municipalities_with_data": [
                        country[y]["municipalities_with_data"] if y in country else None
                        for y in years
                    ],
                }
        return out

    def _territories(self) -> dict[tuple[str, int], dict[str, dict[int, dict]]]:
        out: dict[tuple[str, int], dict[str, dict[int, dict]]] = defaultdict(
            lambda: defaultdict(dict)
        )
        for r in self.v["serve_territory_production"].records():
            out[(r["territory_level"], r["territory_id"])][r["series"]][r["year"]] = r
        return out

    def _climate(self) -> dict[tuple[str, int], dict[str, dict]]:
        years: dict[tuple, list[dict]] = defaultdict(list)
        for r in self.v["serve_climate_territory_year"].records():
            years[(r["territory_level"], r["territory_id"], r["crop"])].append(r)
        summaries = {
            (r["territory_level"], r["territory_id"], r["crop"]): r
            for r in self.v["serve_climate_territory_summary"].records()
        }
        year_columns = [
            c
            for c in self.v["serve_climate_territory_year"].columns
            if c not in ("territory_level", "territory_id", "territory_name", "crop")
        ]
        summary_columns = [
            c
            for c in self.v["serve_climate_territory_summary"].columns
            if c not in ("territory_level", "territory_id", "territory_name", "crop")
        ]
        out: dict[tuple[str, int], dict[str, dict]] = defaultdict(dict)
        for (level, tid, crop), rows in years.items():
            rows.sort(key=lambda r: r["harvest_year"])
            summary = summaries.get((level, tid, crop))
            out[(level, tid)][crop] = {
                "years": columnar(rows, year_columns),
                "summary": {c: summary[c] for c in summary_columns} if summary else None,
            }
        return out

    def places(self) -> dict[str, dict]:
        territories = self._territories()
        climate = self._climate()
        names = {
            (r["territory_level"], r["territory_id"]): r["territory_name"]
            for r in self.v["serve_territory_production"].records()
        }
        states = {m["state_id"]: m["state_abbreviation"] for m in self.municipalities}
        region_state = {m["immediate_region_id"]: m["state_id"] for m in self.municipalities}
        members: dict[int, list[dict]] = defaultdict(list)
        for m in self.municipalities:
            members[m["immediate_region_id"]].append(m)

        def series_blocks(level: str, tid: int) -> dict:
            by_series = territories.get((level, tid), {})
            return {
                s["series"]: self._block(
                    by_series.get(s["series"], {}),
                    s["series"],
                    (*QUANTITIES, "municipalities_with_data", "producing_municipalities"),
                )
                for s in self.series
            }

        out = {}
        levels = {
            "country": [1],
            "macro_region": sorted({m["region_id"] for m in self.municipalities}),
            "state": sorted(states),
            "immediate_region": sorted(members),
        }
        production_rows = self.v["serve_municipality_production"]
        for level, ids in levels.items():
            for tid in ids:
                territory = {"level": level, "id": tid, "name": names.get((level, tid))}
                if territory["name"] is None:  # a territory without any PAM row
                    territory["name"] = self._territory_name(level, tid)
                if level == "state":
                    territory["state_abbreviation"] = states[tid]
                if level == "immediate_region":
                    territory["state_id"] = region_state[tid]
                    territory["state_abbreviation"] = states[region_state[tid]]
                payload = {
                    "meta": None,
                    "territory": territory,
                    "series": series_blocks(level, tid),
                }
                sources = ["ibge_localities", "ibge_pam", "bcb_ipca"]
                if level in ("state", "immediate_region"):
                    payload["climate"] = climate.get((level, tid), {})
                    if payload["climate"]:
                        sources += ["brdwgd", "conab_calendar"]
                if level == "immediate_region":
                    payload["municipalities"] = [
                        {
                            "municipality_id": m["municipality_id"],
                            "municipality_name": m["municipality_name"],
                            "series": {
                                s["series"]: self._municipal_block(
                                    production_rows, s["series"], m["municipality_id"]
                                )
                                for s in self.series
                            },
                        }
                        for m in members[tid]
                    ]
                payload["meta"] = self.ctx.meta("place", sorted(sources))
                path = {
                    "country": "places/country.json",
                    "macro_region": f"places/macro_region/{tid}.json",
                    "state": f"places/state/{states.get(tid)}.json",
                    "immediate_region": f"places/region/{tid}.json",
                }[level]
                out[path] = payload
        return out

    def _territory_name(self, level: str, tid: int) -> str:
        for m in self.municipalities:
            if level == "macro_region" and m["region_id"] == tid:
                return m["region_name"]
            if level == "state" and m["state_id"] == tid:
                return m["state_name"]
            if level == "immediate_region" and m["immediate_region_id"] == tid:
                return m["immediate_region_name"]
        return "Brasil"

    def _municipal_block(self, rows: Rows, series: str, municipality_id: int) -> dict:
        by_year = {
            y: dict(zip(rows.columns, row, strict=True))
            for y, row in self._production.get(series, {}).get(municipality_id, {}).items()
        }
        return self._block(by_year, series, (*QUANTITIES, *RANKS))

    def analysis(self) -> dict:
        def table(view: str, sort: list[str], drop: tuple[str, ...] = (), where=None) -> dict:
            rows = self.v[view].records()
            if where:
                rows = [r for r in rows if where(r)]
            rows.sort(key=lambda r: tuple(r[c] for c in sort))
            return columnar(rows, [c for c in self.v[view].columns if c not in drop])

        def is_state(r):
            return r["territory_level"] == "state"

        headline = self.v["serve_analysis_headline"].records()
        return {
            "meta": self.ctx.meta(
                "analysis",
                ["brdwgd", "conab_calendar", "ibge_localities", "ibge_mesh", "ibge_pam"],
            ),
            "headline": headline[0] if headline else None,
            "climate_yield_by_state": table(
                "serve_climate_territory_year",
                ["crop", "territory_id", "harvest_year"],
                drop=("territory_level",),
                where=is_state,
            ),
            "climate_summary_by_state": table(
                "serve_climate_territory_summary",
                ["crop", "territory_id"],
                drop=("territory_level",),
                where=is_state,
            ),
            "growth_decomposition": table(
                "serve_growth_decomposition",
                ["series", "territory_level", "territory_id", "start_anchor", "end_anchor"],
            ),
            "concentration": table("serve_concentration", ["series", "year"]),
            "coffee_mg_biennial": table("serve_coffee_mg_biennial", ["series", "year"]),
            "soybean_frontier": {
                "shares": table(
                    "serve_soybean_frontier_shares", ["territory_level", "territory_id", "year"]
                ),
                "centroid": table("serve_soybean_frontier_centroid", ["year"]),
                "thresholds": table(
                    "serve_soybean_frontier_thresholds", ["territory_id", "threshold"]
                ),
            },
        }

    def method(self, dbt_tests: dict | None) -> dict:
        def table(view: str, sort: list[str]) -> dict:
            rows = sorted(self.v[view].records(), key=lambda r: tuple(r[c] for c in sort))
            return columnar(rows, self.v[view].columns)

        return {
            "meta": self.ctx.meta("method", ["conab_series", "ibge_pam"]),
            "parameters": self.parameters,
            "validation": {
                "sidra_summary": table(
                    "serve_validation_sidra_summary", ["territory_level", "variable", "status"]
                ),
                "sidra_discrepancies": table(
                    "serve_validation_sidra_discrepancies",
                    ["territory_level", "territory_id", "year", "series", "variable"],
                ),
                "sidra_scope": table("serve_validation_sidra_scope", ["sort_order"]),
                "sidra_definition_pt": SIDRA_COMPARED_CELL_DEFINITION_PT,
                "conab": table("serve_validation_conab", ["state_abbreviation", "harvest_year"]),
            },
            "dbt_tests": dbt_tests,
        }

    def data_files(self, dbt_tests: dict | None) -> dict[str, dict]:
        files = {
            "catalog.json": self.catalog(),
            "municipalities.json": self.municipalities_index(),
            "analysis.json": self.analysis(),
            "method.json": self.method(dbt_tests),
        }
        files.update(self.explore())
        files.update(self.places())
        return files

    def state_abbreviations(self) -> dict[int, str]:
        return {m["state_id"]: m["state_abbreviation"] for m in self.municipalities}
