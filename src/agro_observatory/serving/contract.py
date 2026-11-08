"""Contract of the published files: JSON Schema validation, structure and validity rules.

The JSON Schemas (schemas/*.schema.json, Draft 2020-12) describe every file type. JSON Schema
cannot say that the arrays of a columnar table have the same length, or rules that span
fields, so `check_file` adds those structural checks, and `check_rules` checks the validity
rules of the product (docs/CONTRATO_DE_DADOS.md) across the whole bundle:
- no climate, anomaly or association field at the municipal level;
- coffee: no published series crosses the 2002 unit break, arabica and canephora from 2012,
  and the raw "coffee_total" never appears;
- climate only for soybean and arabica coffee (corn out of the climate analysis);
- "no data" is null, never zero: arrays are dense and aligned with their years, and the real
  value starts at its own first year.
"""

from __future__ import annotations

import json
import re
from functools import cache
from importlib import resources

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

SCHEMA_FILES = (
    "common",
    "catalog",
    "municipalities",
    "explore",
    "place",
    "analysis",
    "method",
    "topology",
    "manifest",
)
FORBIDDEN_MUNICIPAL_KEY = re.compile(r"anomal|_z$|corr|hit_rate|deficit|stress|frost|climate|trend")
COFFEE_BREAKDOWN_FIRST_YEAR = 2012


class ContractError(ValueError):
    pass


@cache
def _schemas() -> dict[str, dict]:
    folder = resources.files("agro_observatory.serving") / "schemas"
    return {name: json.loads((folder / f"{name}.schema.json").read_text()) for name in SCHEMA_FILES}


@cache
def _validators() -> dict[str, Draft202012Validator]:
    schemas = _schemas()
    registry = Registry().with_resources(
        (f"{name}.schema.json", Resource.from_contents(schema)) for name, schema in schemas.items()
    )
    return {
        name: Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
        for name, schema in schemas.items()
        if name != "common"
    }


def schema_errors(payload: dict) -> list[str]:
    name = (payload.get("meta") or {}).get("schema")
    validator = _validators().get(name)
    if validator is None:
        return [f"unknown schema {name!r}"]
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message[:200]}"
        for e in sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))[:20]
    ]


def _equal_lengths(table: dict, where: str, errors: list[str]) -> int | None:
    lengths = {k: len(v) for k, v in table.items() if isinstance(v, list)}
    if len(set(lengths.values())) > 1:
        errors.append(f"{where}: columns of different lengths {lengths}")
        return None
    return next(iter(lengths.values()), 0)


def _aligned(block: dict, where: str, errors: list[str]) -> None:
    """A series block: every array aligned with `years`, the real value with its own years."""
    n = len(block["years"])
    for key, value in block.items():
        if isinstance(value, list) and len(value) != n:
            errors.append(f"{where}.{key}: {len(value)} values for {n} years")
    real = block["real_value"]
    if len(real["production_value_real_thousand_brl"]) != len(real["years"]):
        errors.append(f"{where}.real_value: values and years differ in length")
    for years in (block["years"], real["years"]):
        if years and years != list(range(years[0], years[0] + len(years))):
            errors.append(f"{where}: years are not consecutive")


def check_file(path: str, payload: dict) -> list[str]:
    """Schema and structural errors of one file (empty when it is valid)."""
    errors = schema_errors(payload)
    if errors:
        return [f"{path}: {e}" for e in errors]
    schema = payload["meta"]["schema"]
    if schema == "catalog":
        for key in ("series", "measures"):
            _equal_lengths(payload[key], f"{path}:{key}", errors)
    elif schema == "municipalities":
        for key in ("municipalities", "states", "immediate_regions", "macro_regions"):
            _equal_lengths(payload[key], f"{path}:{key}", errors)
        ids = payload["municipalities"]["municipality_id"]
        if ids != sorted(set(ids)):
            errors.append(f"{path}: municipalities are not in ascending, unique code order")
    elif schema == "explore":
        n = len(payload["years"])
        if len(payload["values"]) != payload["municipality_count"]:
            errors.append(
                f"{path}: {len(payload['values'])} rows for "
                f"{payload['municipality_count']} municipalities"
            )
        if any(len(row) != n for row in payload["values"]):
            errors.append(f"{path}: a municipality row does not have one value per year")
        for key in ("country_total", "municipalities_with_data"):
            if len(payload[key]) != n:
                errors.append(f"{path}:{key}: not one value per year")
    elif schema == "place":
        for series, block in payload["series"].items():
            _aligned(block, f"{path}:series.{series}", errors)
        for crop, climate in payload.get("climate", {}).items():
            _equal_lengths(climate["years"], f"{path}:climate.{crop}.years", errors)
        for m in payload.get("municipalities", []):
            for series, block in m["series"].items():
                _aligned(block, f"{path}:{m['municipality_id']}.{series}", errors)
    elif schema == "analysis":
        for key, value in payload.items():
            if key in ("meta", "headline"):
                continue
            tables = value.items() if key == "soybean_frontier" else [(key, value)]
            for name, table in tables:
                _equal_lengths(table, f"{path}:{name}", errors)
    elif schema == "method":
        validation = payload["validation"]
        for name, table in validation.items():
            if isinstance(table, dict):
                _equal_lengths(table, f"{path}:validation.{name}", errors)
        scope = dict(
            zip(
                validation["sidra_scope"]["category"],
                validation["sidra_scope"]["cells"],
                strict=True,
            )
        )
        if sum(validation["sidra_summary"]["cells"]) != scope.get("compared", 0):
            errors.append(
                f"{path}: the summary counts {sum(validation['sidra_summary']['cells'])} compared "
                f"cells, the scope {scope.get('compared', 0)}"
            )
    return [f"{path}: {e}" if not e.startswith(path) else e for e in errors]


def _walk(value, keys: set[str], strings: set[str]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            keys.add(k)
            _walk(v, keys, strings)
    elif isinstance(value, list):
        for v in value:
            _walk(v, keys, strings)
    elif isinstance(value, str):
        strings.add(value)


def _series_years_ok(
    series: str, years: list[int], catalog: dict, where: str, errors: list[str]
) -> None:
    if not years:
        return
    table = catalog["series"]
    index = table["series"].index(series)
    first, last = table["first_year"][index], table["last_year"][index]
    break_year = catalog["parameters"]["coffee_unit_break_year"]
    if years[0] < first or years[-1] > last:
        errors.append(f"{where}: years {years[0]}–{years[-1]} outside the series {first}–{last}")
    if series == "coffee_in_husk" and years[-1] >= break_year:
        errors.append(f"{where}: coffee in husk reaches {years[-1]} (break in {break_year})")
    if series == "coffee_processed" and years[0] < break_year:
        errors.append(f"{where}: processed coffee starts in {years[0]} (break in {break_year})")
    if series in ("coffee_arabica", "coffee_canephora") and years[0] < COFFEE_BREAKDOWN_FIRST_YEAR:
        errors.append(f"{where}: {series} starts in {years[0]}")


def check_rules(files: dict[str, dict]) -> list[str]:
    """Validity rules of the product across the bundle (empty when they all hold)."""
    errors: list[str] = []
    catalog = files["catalog.json"]
    real_first = dict(
        zip(catalog["series"]["series"], catalog["series"]["real_value_first_year"], strict=True)
    )
    for path, payload in files.items():
        if payload["meta"]["schema"] in ("topology", "manifest"):
            continue
        keys: set[str] = set()
        strings: set[str] = set()
        _walk(payload, keys, strings)
        if "coffee_total" in strings or "coffee_total" in keys:
            errors.append(f"{path}: the raw coffee_total series is published")
        schema = payload["meta"]["schema"]
        if schema == "explore":
            municipal_keys = set(payload)
            bad = sorted(k for k in municipal_keys if FORBIDDEN_MUNICIPAL_KEY.search(k))
            if bad:
                errors.append(f"{path}: climate or association fields in a municipal file: {bad}")
            _series_years_ok(payload["series"], payload["years"], catalog, path, errors)
            if (
                payload["measure"] == "production_value_real_thousand_brl"
                and payload["years"][0] != real_first[payload["series"]]
            ):
                errors.append(f"{path}: real value starts in {payload['years'][0]}")
        if schema == "place":
            for series, block in payload["series"].items():
                _series_years_ok(series, block["years"], catalog, f"{path}:{series}", errors)
                if block["real_value"]["years"][:1] != [real_first[series]]:
                    errors.append(
                        f"{path}:{series}: real value does not start in {real_first[series]}"
                    )
            for crop in payload.get("climate", {}):
                if crop not in ("soybean", "coffee_arabica"):
                    errors.append(f"{path}: climate for {crop}")
            for m in payload.get("municipalities", []):
                keys = set()
                _walk(m, keys, set())
                bad = sorted(k for k in keys if FORBIDDEN_MUNICIPAL_KEY.search(k))
                if bad:
                    errors.append(
                        f"{path}:{m['municipality_id']}: climate or association fields {bad}"
                    )
                for series, block in m["series"].items():
                    _series_years_ok(
                        series,
                        block["years"],
                        catalog,
                        f"{path}:{m['municipality_id']}.{series}",
                        errors,
                    )
        if schema == "analysis":
            for table in ("climate_yield_by_state", "climate_summary_by_state"):
                crops = set(payload[table]["crop"])
                if not crops <= {"soybean", "coffee_arabica"}:
                    errors.append(f"{path}:{table}: climate for {sorted(crops)}")
            for table in ("concentration", "coffee_mg_biennial"):
                t = payload[table]
                by_series: dict[str, list[int]] = {}
                for s, y in zip(t["series"], t["year"], strict=True):
                    by_series.setdefault(s, []).append(y)
                for s, years in by_series.items():
                    _series_years_ok(s, sorted(years), catalog, f"{path}:{table}.{s}", errors)
            d = payload["growth_decomposition"]
            for s, start, end in zip(d["series"], d["start_anchor"], d["end_anchor"], strict=True):
                _series_years_ok(
                    s, [start - 1, end + 1], catalog, f"{path}:growth_decomposition.{s}", errors
                )
    return errors


def check_all(files: dict[str, dict]) -> list[str]:
    errors = []
    for path, payload in files.items():
        errors.extend(check_file(path, payload))
    if not errors:
        errors.extend(check_rules(files))
    return errors
