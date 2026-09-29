from datetime import UTC, date, datetime

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from agro_observatory import load_raw
from agro_observatory.load_raw import SOURCES, Kind, SchemaMismatchError

INGESTED_AT = datetime(2026, 1, 1, tzinfo=UTC)
LOADED_AT = datetime(2026, 2, 1, tzinfo=UTC)


def sample_table() -> pa.Table:
    return pa.table(
        {
            "V": pa.array(["1850", None], pa.string()),
            "D1C": pa.array(["1100015", "1100023"], pa.string()),
            "_ingested_at": pa.array([INGESTED_AT] * 2, pa.timestamp("us", tz="UTC")),
        }
    )


def touch(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def test_find_files_lists_pam_partitions_in_order(tmp_path) -> None:
    for crop, year in [("soybean", 2001), ("corn", 1999), ("corn", 2000)]:
        touch(tmp_path / "pam" / f"crop={crop}" / f"year={year}" / "data.parquet")
    touch(tmp_path / "pam" / "crop=corn" / "year=2001" / "data.parquet.tmp")

    files = load_raw.find_files(SOURCES["pam"], tmp_path)

    assert [f.relative_to(tmp_path).as_posix() for f in files] == [
        "pam/crop=corn/year=1999/data.parquet",
        "pam/crop=corn/year=2000/data.parquet",
        "pam/crop=soybean/year=2001/data.parquet",
    ]


def test_find_files_fails_when_source_was_not_ingested(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load_raw.find_files(SOURCES["ipca"], tmp_path)


def test_postgres_columns_mirror_parquet_plus_load_metadata() -> None:
    assert load_raw.postgres_columns(sample_table().schema, SOURCES["pam"]) == [
        ("V", "text"),
        ("D1C", "text"),
        ("_ingested_at", "timestamptz"),
        ("_source_file", "text"),
        ("_loaded_at", "timestamptz"),
    ]


def test_postgres_columns_reject_typed_source_columns() -> None:
    with pytest.raises(SchemaMismatchError, match="unsupported"):
        load_raw.postgres_columns(pa.schema([("valor", pa.float64())]), SOURCES["ipca"])


def test_create_table_sql_quotes_identifiers() -> None:
    columns = [("D1C", "text"), ("regiao-imediata__id", "text"), ("_loaded_at", "timestamptz")]

    assert load_raw.create_table_sql("localities", columns).as_string(None) == (
        'CREATE TABLE IF NOT EXISTS "raw"."localities" '
        '("D1C" text, "regiao-imediata__id" text, "_loaded_at" timestamptz)'
    )


def test_copy_sql_lists_columns() -> None:
    assert load_raw.copy_sql("pam", ["V", "_source_file"]).as_string(None) == (
        'COPY "raw"."pam" ("V", "_source_file") FROM STDIN'
    )


def test_clear_sql_deletes_partition_for_pam_and_truncates_snapshots() -> None:
    assert load_raw.clear_sql(SOURCES["pam"]).as_string(None) == (
        'DELETE FROM "raw"."pam" WHERE _source_file = %s'
    )
    assert load_raw.clear_sql(SOURCES["ipca"]).as_string(None) == 'TRUNCATE "raw"."ipca"'


def test_iter_rows_appends_load_metadata_and_keeps_nulls() -> None:
    rows = list(load_raw.iter_rows(sample_table(), "pam/x.parquet", LOADED_AT))

    assert rows == [
        ("1850", "1100015", INGESTED_AT, "pam/x.parquet", LOADED_AT),
        (None, "1100023", INGESTED_AT, "pam/x.parquet", LOADED_AT),
    ]


def test_conninfo_reads_environment(monkeypatch) -> None:
    for key, value in {
        "POSTGRES_DB": "db",
        "POSTGRES_USER": "u",
        "POSTGRES_PASSWORD": "p",
        "POSTGRES_PORT": "5433",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("POSTGRES_HOST", raising=False)

    conninfo = load_raw.conninfo_from_env()

    assert all(part in conninfo for part in ["host=localhost", "port=5433", "dbname=db", "user=u"])


@pytest.mark.parametrize(
    ("loaded", "force", "expected"),
    [
        ({}, False, True),  # never loaded
        ({"pam/a.parquet": INGESTED_AT}, False, False),  # same version already in the table
        ({"pam/a.parquet": LOADED_AT}, False, True),  # file was re-ingested since last load
        ({"pam/a.parquet": INGESTED_AT}, True, True),  # forced
    ],
)
def test_needs_load(loaded, force, expected) -> None:
    assert load_raw.needs_load("pam/a.parquet", INGESTED_AT, loaded, force) is expected


def test_file_version_reads_ingestion_timestamp(tmp_path) -> None:
    path = tmp_path / "data.parquet"
    pq.write_table(sample_table(), path)

    assert load_raw.file_version(path) == INGESTED_AT


def test_find_orphans_lists_files_only_in_the_table() -> None:
    loaded = ["pam/crop=corn/year=2000/data.parquet", "pam/crop=corn/year=2001/data.parquet"]
    disk = ["pam/crop=corn/year=2001/data.parquet", "pam/crop=corn/year=2002/data.parquet"]

    assert load_raw.find_orphans(loaded, disk) == ["pam/crop=corn/year=2000/data.parquet"]
    assert load_raw.find_orphans(disk[:1], disk) == []


def test_prune_sql_deletes_listed_files() -> None:
    assert load_raw.prune_sql("pam").as_string(None) == (
        'DELETE FROM "raw"."pam" WHERE _source_file = ANY(%s)'
    )


class FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, object]] = []
        self.transactions = 0

    def transaction(self):
        self.transactions += 1
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def execute(self, query, params=None):
        self.executed.append((query.as_string(None), params))
        return type("Result", (), {"rowcount": 42})()


def test_orphans_are_only_reported_without_prune(caplog) -> None:
    conn = FakeConnection()

    load_raw.handle_orphans(conn, SOURCES["pam"], ["pam/old.parquet"], prune=False)

    assert conn.executed == []
    assert "use --prune" in caplog.text
    assert "pam/old.parquet" in caplog.text


def test_orphans_are_deleted_in_a_transaction_with_prune(caplog) -> None:
    conn = FakeConnection()

    load_raw.handle_orphans(conn, SOURCES["pam"], ["pam/old.parquet"], prune=True)

    assert conn.transactions == 1
    assert conn.executed == [
        ('DELETE FROM "raw"."pam" WHERE _source_file = ANY(%s)', (["pam/old.parquet"],))
    ]
    assert "pruned 42 orphan rows" in caplog.text


def test_no_orphans_does_nothing() -> None:
    conn = FakeConnection()

    load_raw.handle_orphans(conn, SOURCES["pam"], [], prune=True)

    assert conn.executed == [] and conn.transactions == 0


def climate_table() -> pa.Table:
    return pa.table(
        {
            "municipality_id": pa.array([5107925, 5107925], pa.int32()),
            "date": pa.array([date(2025, 1, 1), date(2025, 1, 2)], pa.date32()),
            "precipitation_mm": pa.array([12.5, None], pa.float32()),
            "_source_version": pa.array(["v_3.2.4"] * 2, pa.string()),
            "_ingested_at": pa.array([INGESTED_AT] * 2, pa.timestamp("us", tz="UTC")),
        }
    )


def test_typed_year_partitioned_columns_keep_types_and_drop_metadata() -> None:
    columns = load_raw.postgres_columns(climate_table().schema, SOURCES["climate_daily"])

    assert columns == [
        ("municipality_id", "integer"),
        ("date", "date"),
        ("precipitation_mm", "real"),
    ]


def test_typed_snapshot_keeps_types_and_adds_load_metadata() -> None:
    schema = pa.schema([("municipality_id", pa.int32()), ("centroid_lon", pa.float64())])

    assert load_raw.postgres_columns(schema, SOURCES["climate_cells"]) == [
        ("municipality_id", "integer"),
        ("centroid_lon", "double precision"),
        *load_raw.LOAD_COLUMNS,
    ]


def test_partitioned_table_and_year_partition_sql() -> None:
    columns = [("municipality_id", "integer"), ("date", "date")]

    assert load_raw.create_table_sql("t", columns, "date").as_string(None) == (
        'CREATE TABLE IF NOT EXISTS "raw"."t" ("municipality_id" integer, "date" date) '
        'PARTITION BY RANGE ("date")'
    )
    assert load_raw.create_year_partition_sql("t", 1980).as_string(None) == (
        'CREATE TABLE IF NOT EXISTS "raw"."t_1980" PARTITION OF "raw"."t" '
        "FOR VALUES FROM ('1980-01-01') TO ('1981-01-01')"
    )
    assert load_raw.truncate_partition_sql("t", 1980).as_string(None) == 'TRUNCATE "raw"."t_1980"'


def test_year_partitioned_source_cannot_use_row_clear() -> None:
    assert SOURCES["climate_daily"].kind is Kind.YEAR_PARTITIONED
    with pytest.raises(ValueError):
        load_raw.clear_sql(SOURCES["climate_daily"])


def test_year_from_file() -> None:
    assert load_raw.year_from_file("climate/brdwgd_daily/year=1998/data.parquet") == 1998
    with pytest.raises(ValueError):
        load_raw.year_from_file("climate/brdwgd_municipality_cells.parquet")


def test_csv_bytes_writes_nulls_as_empty_fields() -> None:
    columns = ["municipality_id", "date", "precipitation_mm"]

    assert load_raw.csv_bytes(climate_table().select(columns)).decode().splitlines() == [
        "5107925,2025-01-01,12.5",
        "5107925,2025-01-02,",
    ]


def test_year_partitioned_orphans_drop_partitions() -> None:
    conn = FakeConnection()
    orphan = "climate/brdwgd_daily/year=1980/data.parquet"

    load_raw.handle_orphans(conn, SOURCES["climate_daily"], [orphan], prune=True)

    assert conn.executed[0] == ('DROP TABLE IF EXISTS "raw"."brdwgd_municipality_daily_1980"', None)
    assert conn.transactions == 1
