"""Ingest the monthly IPCA variation (% per month) from the Central Bank's SGS API.

SGS series 433 matches IBGE's official IPCA monthly variation (SIDRA table 1737, variable 63).
The whole series comes in a single request (the SGS 10-year window limit applies only to
daily series). It is small, so every run re-downloads and replaces it.
"""

import argparse
import logging
import sys
from collections.abc import Callable
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

SERIES_ID = 433
SOURCE_URL = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{SERIES_ID}/dados?formato=json"
DEFAULT_OUTPUT_PATH = Path("data/raw/ipca/ipca.parquet")
SOURCE_COLUMNS = ("data", "valor")


def parse_response(payload: Any) -> list[dict[str, str]]:
    if not isinstance(payload, list) or not payload:
        raise InvalidResponseError("expected a non-empty JSON list of observations")
    for item in payload:
        if not isinstance(item, dict) or tuple(item) != SOURCE_COLUMNS:
            raise InvalidResponseError(f"unexpected observation: {item}")
    return payload


def ingest(fetch_json: Callable[[str], Any], output_path: Path) -> int:
    payload = fetch_json(SOURCE_URL)
    ingested_at = datetime.now(UTC)
    rows = parse_response(payload)
    write_parquet_atomic(raw_table(rows, SOURCE_COLUMNS, SOURCE_URL, ingested_at), output_path)
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="ingest-ipca",
        description="Download the monthly IPCA variation (BCB SGS series 433) into Parquet.",
    )
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args(argv)

    with HttpClient() as client:
        count = ingest(client.get_json, args.output_path)
    logger.info("%d observations written to %s", count, args.output_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
