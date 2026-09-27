from datetime import UTC, datetime

import pyarrow.parquet as pq

from agro_observatory.ingestion.common import raw_table, write_parquet_atomic


def test_raw_table_keeps_text_and_adds_ingestion_metadata() -> None:
    rows = [{"a": "1", "b": None}, {"a": "-", "b": "x"}]
    ingested_at = datetime(2026, 1, 1, tzinfo=UTC)

    table = raw_table(rows, ("a", "b"), "http://example", ingested_at)

    assert table.column_names == ["a", "b", "_source_url", "_ingested_at"]
    assert str(table.schema.field("a").type) == "string"
    assert table.column("b").to_pylist() == [None, "x"]
    assert set(table.column("_source_url").to_pylist()) == {"http://example"}
    assert set(table.column("_ingested_at").to_pylist()) == {ingested_at}


def test_write_parquet_atomic_replaces_file_without_leftovers(tmp_path) -> None:
    path = tmp_path / "nested" / "data.parquet"
    ingested_at = datetime(2026, 1, 1, tzinfo=UTC)

    write_parquet_atomic(raw_table([{"a": "1"}], ("a",), "u", ingested_at), path)
    write_parquet_atomic(raw_table([{"a": "2"}, {"a": "3"}], ("a",), "u", ingested_at), path)

    assert pq.read_table(path).column("a").to_pylist() == ["2", "3"]
    assert [p.name for p in path.parent.iterdir()] == ["data.parquet"]
