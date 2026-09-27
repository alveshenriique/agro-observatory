import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from agro_observatory.ingestion import ipca
from agro_observatory.ingestion.common import InvalidResponseError

FIXTURE = Path(__file__).parent / "fixtures" / "sgs_ipca_sample.json"


@pytest.fixture
def payload() -> list[dict[str, str]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_source_url_requests_full_series() -> None:
    assert ipca.SOURCE_URL == "https://api.bcb.gov.br/dados/serie/bcdata.sgs.433/dados?formato=json"


def test_parse_response_keeps_values_as_text(payload) -> None:
    rows = ipca.parse_response(payload)

    assert rows[0] == {"data": "01/01/1980", "valor": "6.62"}


@pytest.mark.parametrize("bad", [[], {"erro": "x"}, [{"data": "01/01/1980"}], ["x"]])
def test_parse_response_rejects_malformed_payload(bad) -> None:
    with pytest.raises(InvalidResponseError):
        ipca.parse_response(bad)


def test_ingest_replaces_previous_file(tmp_path, payload) -> None:
    output = tmp_path / "ipca.parquet"

    assert ipca.ingest(lambda url: payload, output) == 3
    assert ipca.ingest(lambda url: payload[:2], output) == 2

    table = pq.read_table(output)
    assert table.column("data").to_pylist() == ["01/01/1980", "01/02/1980"]
    assert set(table.column("_source_url").to_pylist()) == {ipca.SOURCE_URL}
