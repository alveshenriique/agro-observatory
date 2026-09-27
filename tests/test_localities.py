import copy
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from agro_observatory.ingestion import localities
from agro_observatory.ingestion.common import InvalidResponseError

FIXTURE = Path(__file__).parent / "fixtures" / "ibge_municipalities_sample.json"


@pytest.fixture
def payload() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def by_name(rows: list[dict], name: str) -> dict:
    return next(row for row in rows if row["nome"] == name)


def test_flattens_full_hierarchy_as_text(payload) -> None:
    rows = localities.parse_response(payload)
    bh = by_name(rows, "Belo Horizonte")

    assert list(bh) == list(localities.SOURCE_COLUMNS)
    assert bh["id"] == "3106200"
    assert bh["microrregiao__mesorregiao__UF__sigla"] == "MG"
    assert bh["regiao-imediata__regiao-intermediaria__UF__regiao__nome"] == "Sudeste"
    assert all(v is None or isinstance(v, str) for v in bh.values())


def test_null_branch_becomes_null_columns(payload) -> None:
    # Boa Esperança do Norte (MT) comes without microrregiao in the real API response.
    row = by_name(localities.parse_response(payload), "Boa Esperança do Norte")

    micro_columns = [c for c in localities.SOURCE_COLUMNS if c.startswith("microrregiao")]
    assert all(row[c] is None for c in micro_columns)
    assert row["regiao-imediata__nome"] == "Sorriso"


def test_rejects_unexpected_field(payload) -> None:
    changed = copy.deepcopy(payload)
    changed[0]["microrregiao"]["mesorregiao"]["novo_campo"] = "x"

    with pytest.raises(InvalidResponseError, match="novo_campo"):
        localities.parse_response(changed)


def test_rejects_duplicate_ids(payload) -> None:
    with pytest.raises(InvalidResponseError, match="duplicate"):
        localities.parse_response(payload + payload[:1])


def test_ingest_replaces_previous_snapshot(tmp_path, payload) -> None:
    output = tmp_path / "municipalities.parquet"

    assert localities.ingest(lambda url: payload, output) == 3
    assert localities.ingest(lambda url: payload[:2], output) == 2
    assert pq.read_table(output).num_rows == 2
