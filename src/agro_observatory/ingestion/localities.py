"""Ingest IBGE's municipality list with its full territorial hierarchy (Localidades API).

The nested JSON is flattened into one column per leaf field, named after the API path
joined by "__" (e.g. "microrregiao__mesorregiao__UF__sigla"). Each run takes a snapshot
of the current territorial grid and replaces the previous one.
"""

import argparse
import logging
import sys
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agro_observatory.http_client import HttpClient
from agro_observatory.ingestion.common import (
    InvalidResponseError,
    configure_logging,
    raw_table,
    write_parquet_atomic,
)

logger = logging.getLogger(__name__)

MUNICIPALITIES_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
DEFAULT_OUTPUT_PATH = Path("data/raw/localities/municipalities.parquet")
SEP = "__"

_UF = ("UF__id", "UF__sigla", "UF__nome", "UF__regiao__id", "UF__regiao__sigla", "UF__regiao__nome")
_MICRO = "microrregiao"
_MESO = f"{_MICRO}{SEP}mesorregiao"
_IMMEDIATE = "regiao-imediata"
_INTERMEDIATE = f"{_IMMEDIATE}{SEP}regiao-intermediaria"

SOURCE_COLUMNS = (
    "id",
    "nome",
    f"{_MICRO}{SEP}id",
    f"{_MICRO}{SEP}nome",
    f"{_MESO}{SEP}id",
    f"{_MESO}{SEP}nome",
    *(f"{_MESO}{SEP}{c}" for c in _UF),
    f"{_IMMEDIATE}{SEP}id",
    f"{_IMMEDIATE}{SEP}nome",
    f"{_INTERMEDIATE}{SEP}id",
    f"{_INTERMEDIATE}{SEP}nome",
    *(f"{_INTERMEDIATE}{SEP}{c}" for c in _UF),
)
REQUIRED_COLUMNS = ("id", "nome")


def _leaves(obj: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            yield from _leaves(value, f"{prefix}{SEP}{key}" if prefix else key)
    else:
        yield prefix, obj


def flatten_municipality(record: Mapping[str, Any]) -> dict[str, str | None]:
    """Flatten one municipality; a null branch (e.g. no microrregiao) yields null columns."""
    row: dict[str, str | None] = dict.fromkeys(SOURCE_COLUMNS)
    for path, value in _leaves(record):
        if path in row:
            row[path] = None if value is None else str(value)
        elif not (value is None and any(c.startswith(path + SEP) for c in SOURCE_COLUMNS)):
            raise InvalidResponseError(f"unexpected field in municipality: {path}")

    missing = [c for c in REQUIRED_COLUMNS if row[c] is None]
    if missing:
        raise InvalidResponseError(f"municipality without {missing}: {record}")
    return row


def parse_response(payload: Any) -> list[dict[str, str | None]]:
    if not isinstance(payload, list) or not payload:
        raise InvalidResponseError("expected a non-empty JSON list of municipalities")
    rows = [flatten_municipality(record) for record in payload]

    ids = [row["id"] for row in rows]
    if len(set(ids)) != len(ids):
        raise InvalidResponseError("duplicate municipality ids in response")
    return rows


def ingest(fetch_json: Callable[[str], Any], output_path: Path) -> int:
    payload = fetch_json(MUNICIPALITIES_URL)
    ingested_at = datetime.now(UTC)
    rows = parse_response(payload)

    incomplete = [row["nome"] for row in rows if None in row.values()]
    if incomplete:
        logger.warning("municipalities with missing hierarchy levels: %s", incomplete)

    table = raw_table(rows, SOURCE_COLUMNS, MUNICIPALITIES_URL, ingested_at)
    write_parquet_atomic(table, output_path)
    return table.num_rows


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="ingest-localities",
        description="Snapshot IBGE municipalities with their territorial hierarchy into Parquet.",
    )
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args(argv)

    with HttpClient() as client:
        count = ingest(client.get_json, args.output_path)
    logger.info("%d municipalities written to %s", count, args.output_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
