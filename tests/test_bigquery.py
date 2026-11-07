"""BigQuery backend, quota safety lock and window-indicator export (no network)."""

import io
from datetime import UTC, datetime
from decimal import Decimal

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from agro_observatory import bigquery_ops as ops
from agro_observatory import bq_dbt, export_window_indicators, load_raw, load_raw_bigquery

T0 = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
T1 = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def write_raw(path, rows, url, ingested_at, extra=None):
    data = {"V": [r[0] for r in rows], "D1C": [r[1] for r in rows]}
    data.update(extra or {})
    data["_source_url"] = [url] * len(rows)
    data["_ingested_at"] = pa.array([ingested_at] * len(rows), pa.timestamp("us", tz="UTC"))
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(data), path)


# --- quota helpers --------------------------------------------------------------------------


def test_logical_bytes_follows_bigquery_sizing() -> None:
    table = pa.table(
        {
            "s": pa.array(["ab", None, "çé"], pa.string()),  # (2+2) + (2+4) = 10, null free
            "i": pa.array([1, 2, None], pa.int32()),  # 2 x 8
            "f": pa.array([1.5, 2.5, 3.5], pa.float32()),  # 3 x 8
            "n": pa.array([Decimal("0.5")], pa.decimal128(38, 9)).take([0, 0, 0]),  # 3 x 16
            "b": pa.array([True, False, None]),  # 2 x 1
        }
    )
    assert ops.logical_bytes(table) == 10 + 16 + 24 + 48 + 2


def test_arrow_kind_rejects_unsupported_types() -> None:
    with pytest.raises(TypeError):
        ops.arrow_kind(pa.list_(pa.int32()))


def test_quota_log_appends_and_sums(tmp_path) -> None:
    log = tmp_path / "quota.csv"
    assert ops.read_quota_log(log) == ops.QuotaStatus(0, 0)
    ops.append_quota_log("load-raw", "pam", 100, 90, log)
    ops.append_quota_log("dbt build", "all", 50, 60, log)
    status = ops.read_quota_log(log)
    assert (status.used_bytes, status.entries) == (150, 2)
    assert status.remaining_bytes == ops.LIFETIME_QUOTA_BYTES - 150
    assert log.read_text().splitlines()[0] == ",".join(ops.QUOTA_LOG_FIELDS)


def test_quota_report_shows_estimate_used_and_remaining() -> None:
    report = ops.quota_report(10 * ops.MIB, ops.QuotaStatus(20 * ops.MIB, 1))
    assert "Estimated write: 10.0 MiB" in report and "used so far" in report
    assert "after this operation: 30.0 MiB" in report


class FakeStdin(io.StringIO):
    def __init__(self, tty: bool):
        super().__init__()
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


def test_confirm_write_requires_yes_when_not_interactive() -> None:
    with pytest.raises(ops.NotConfirmedError):
        ops.confirm_write("summary", yes=False, stdin=FakeStdin(tty=False))
    ops.confirm_write("summary", yes=True, stdin=FakeStdin(tty=False))


@pytest.mark.parametrize(("answer", "accepted"), [("yes", True), ("YES", True), ("no", False)])
def test_confirm_write_interactive(monkeypatch, answer, accepted) -> None:
    monkeypatch.setattr("builtins.input", lambda _: answer)
    if accepted:
        ops.confirm_write("summary", yes=False, stdin=FakeStdin(tty=True))
    else:
        with pytest.raises(ops.NotConfirmedError):
            ops.confirm_write("summary", yes=False, stdin=FakeStdin(tty=True))


def test_bigquery_settings_require_the_project(monkeypatch) -> None:
    monkeypatch.delenv("BIGQUERY_PROJECT", raising=False)
    with pytest.raises(SystemExit):
        ops.bigquery_settings()
    monkeypatch.setenv("BIGQUERY_PROJECT", "p")
    monkeypatch.delenv("BIGQUERY_LOCATION", raising=False)
    assert ops.bigquery_settings() == ("p", "southamerica-east1")


# --- BigQuery load-raw backend --------------------------------------------------------------


def test_bigquery_column_name_replaces_hyphens() -> None:
    assert load_raw_bigquery.bigquery_column_name("regiao-imediata__id") == "regiao_imediata__id"
    assert load_raw_bigquery.bigquery_column_name("D1C") == "D1C"


def test_prepare_table_moves_source_url_to_the_manifest(tmp_path) -> None:
    source = load_raw.SOURCES["pam"]
    a = tmp_path / "pam/crop=soybean/year=2024/data.parquet"
    b = tmp_path / "pam/crop=soybean/year=2025/data.parquet"
    write_raw(a, [("10", "1"), ("-", "2")], "https://x/2024", T0, {"regiao-imediata": ["r", "s"]})
    write_raw(b, [("...", "1")], "https://x/2025", T1, {"regiao-imediata": ["r"]})
    prepared = load_raw_bigquery.prepare_table(source, [a, b], tmp_path, T1)

    table = prepared.table
    assert table.num_rows == 3
    assert "_source_url" not in table.column_names
    assert table.column_names == ["V", "D1C", "regiao_imediata", "_ingested_at", "_loaded_at"]
    assert table.column("_loaded_at").to_pylist() == [T1] * 3
    assert [(m["source_file"], m["source_url"], m["row_count"]) for m in prepared.manifest] == [
        ("pam/crop=soybean/year=2024/data.parquet", "https://x/2024", 2),
        ("pam/crop=soybean/year=2025/data.parquet", "https://x/2025", 1),
    ]
    assert [m["ingested_at"] for m in prepared.manifest] == [T0, T1]


def manifest_of(*files):
    return load_raw_bigquery.PreparedTable(
        load_raw.SOURCES["pam"],
        pa.table({"x": [1]}),
        [{"source_file": f, "ingested_at": t} for f, t in files],
    )


@pytest.mark.parametrize(
    ("loaded", "exists", "expected"),
    [
        ({"a": T0, "b": T1}, True, False),  # unchanged
        ({"a": T0, "b": T1}, False, True),  # table expired or never loaded
        ({"a": T0, "b": T0}, True, True),  # one file re-ingested
        ({"a": T0}, True, True),  # a new file
        ({"a": T0, "b": T1, "c": T1}, True, True),  # a file removed from disk
    ],
)
def test_needs_reload(loaded, exists, expected) -> None:
    prepared = manifest_of(("a", T0), ("b", T1))
    assert load_raw_bigquery.needs_reload(prepared, loaded, exists) is expected


def test_merge_manifest_replaces_only_the_reloaded_tables() -> None:
    def row(table, file):
        return {
            "table_name": table,
            "source_file": file,
            "source_url": None,
            "ingested_at": T0,
            "loaded_at": T0,
            "row_count": 1,
        }

    existing = [row("pam", "old"), row("ipca", "ipca.parquet")]
    merged = load_raw_bigquery.merge_manifest(existing, [row("pam", "new")], {"pam"})
    assert merged.schema == load_raw_bigquery.MANIFEST_SCHEMA
    assert sorted(
        zip(merged["table_name"].to_pylist(), merged["source_file"].to_pylist(), strict=True)
    ) == [
        ("ipca", "ipca.parquet"),
        ("pam", "new"),
    ]


def test_bigquery_schema_maps_arrow_types() -> None:
    schema = pa.schema(
        [
            ("s", pa.string()),
            ("i", pa.int32()),
            ("f", pa.float32()),
            ("n", pa.decimal128(38, 9)),
            ("t", pa.timestamp("us", tz="UTC")),
            ("d", pa.date32()),
        ]
    )
    fields = load_raw_bigquery.bigquery_schema(schema)
    assert [(f.name, f.field_type) for f in fields] == [
        ("s", "STRING"),
        ("i", "INT64"),
        ("f", "FLOAT64"),
        ("n", "NUMERIC"),
        ("t", "TIMESTAMP"),
        ("d", "DATE"),
    ]


def test_bigquery_rejects_the_daily_climate_before_connecting(tmp_path) -> None:
    with pytest.raises(SystemExit, match="lean architecture"):
        load_raw_bigquery.run(["climate_daily"], tmp_path, False, False, True)


def test_default_sources_per_target() -> None:
    assert "climate_window_indicators" not in load_raw.DEFAULT_SOURCES["postgres"]
    assert "climate_daily" in load_raw.DEFAULT_SOURCES["postgres"]
    assert "climate_daily" not in load_raw.DEFAULT_SOURCES["bigquery"]
    assert "climate_window_indicators" in load_raw.DEFAULT_SOURCES["bigquery"]


@pytest.mark.parametrize("flag", ["--yes", "--empty"])
def test_bigquery_flags_are_rejected_on_postgres(flag) -> None:
    with pytest.raises(SystemExit) as exc:
        load_raw.main([flag])
    assert exc.value.code == 2


def test_typed_snapshot_maps_decimal_to_numeric() -> None:
    schema = pa.schema([("coverage", pa.decimal128(38, 9)), ("tmin_min_c", pa.float32())])
    columns = load_raw.postgres_columns(schema, load_raw.SOURCES["climate_window_indicators"])
    assert columns[:2] == [("coverage", "numeric"), ("tmin_min_c", "real")]


# --- window-indicator export ----------------------------------------------------------------


def test_export_reproduces_postgres_types() -> None:
    columns = [
        ("municipality_id", 23),
        ("crop", 25),
        ("days_with_data", 20),
        ("coverage", 1700),
        ("precipitation_mm", 700),
        ("tmax_mean_c", 701),
    ]
    rows = [
        (1, "soybean", 120, Decimal("0.9917"), 512.25, 31.123456789),
        (2, "soybean", 3, None, None, None),
    ]
    table = export_window_indicators.to_arrow(columns, rows, T1)
    assert [str(f.type) for f in table.schema][:6] == [
        "int32",
        "string",
        "int64",
        "decimal128(38, 9)",
        "float",
        "double",
    ]
    assert table.column("coverage").to_pylist() == [Decimal("0.991700000"), None]
    assert table.column("_ingested_at").to_pylist() == [T1, T1]
    assert table.column("_source_url")[0].as_py() == export_window_indicators.SOURCE_URL


def test_export_rejects_unknown_types() -> None:
    with pytest.raises(TypeError):
        export_window_indicators.to_arrow([("x", 3802)], [({},)], T1)  # jsonb


# --- bq-dbt -----------------------------------------------------------------------------------


def test_selection_args_keep_only_node_selection() -> None:
    args = ["--empty", "--select", "fct_crop_production+", "dim_year", "--fail-fast"]
    assert bq_dbt.selection_args(args) == ["--select", "fct_crop_production+", "dim_year"]
    assert bq_dbt.selection_args(["-s", "a", "--exclude", "b"]) == ["-s", "a", "--exclude", "b"]


def test_only_tables_and_seeds_use_storage() -> None:
    assert bq_dbt.writes_storage({"resource_type": "seed", "materialized": "seed"})
    assert bq_dbt.writes_storage({"resource_type": "model", "materialized": "table"})
    assert not bq_dbt.writes_storage({"resource_type": "model", "materialized": "view"})


def test_estimate_is_zero_with_empty() -> None:
    nodes = [{"resource_type": "model", "materialized": "table", "schema": "marts", "name": "x"}]
    size, lines = bq_dbt.estimate(nodes, empty=True)
    assert size == 0 and "--empty" in lines[0]
