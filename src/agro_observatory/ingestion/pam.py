"""Ingest IBGE's Produção Agrícola Municipal (SIDRA table 5457) into raw Parquet files.

One request per (crop, year) with all municipalities and variables, saved to
data/raw/pam/crop=<crop>/year=<year>/data.parquet. Values are kept exactly as
returned by the API (text, including special symbols such as "-" and "...").
"""

import argparse
import logging
import os
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from agro_observatory.http_client import HttpClient

logger = logging.getLogger(__name__)

SIDRA_VALUES_URL = "https://apisidra.ibge.gov.br/values"
METADATA_URL = "https://servicodados.ibge.gov.br/api/v3/agregados/5457/metadados"
TABLE_ID = 5457
PRODUCT_CLASSIFICATION_ID = 782
# Planted area, harvested area, quantity produced, average yield, production value.
VARIABLE_IDS = (8331, 216, 214, 112, 215)
# IBGE revises the most recent PAM releases, so these years are always re-downloaded.
REVISED_YEARS = 2
DEFAULT_OUTPUT_DIR = Path("data/raw/pam")

# Keys of each row in the SIDRA response, in API order.
SOURCE_COLUMNS = (
    "NC", "NN", "MC", "MN", "V", "D1C", "D1N", "D2C", "D2N", "D3C", "D3N", "D4C", "D4N",
)  # fmt: skip


@dataclass(frozen=True)
class Crop:
    slug: str
    product_id: int
    first_year: int


CROPS = {
    crop.slug: crop
    for crop in (
        Crop("soybean", 40124, 1974),
        Crop("corn", 40122, 1974),
        Crop("coffee_total", 40139, 1974),
        # Arabica/canephora split is only published from 2012 on (earlier years are all "...").
        Crop("coffee_arabica", 40140, 2012),
        Crop("coffee_canephora", 40141, 2012),
    )
}


@dataclass(frozen=True)
class Task:
    crop: Crop
    year: int


class InvalidResponseError(ValueError):
    pass


def build_url(crop: Crop, year: int) -> str:
    variables = ",".join(str(v) for v in VARIABLE_IDS)
    return (
        f"{SIDRA_VALUES_URL}/t/{TABLE_ID}/n6/all/v/{variables}"
        f"/p/{year}/c{PRODUCT_CLASSIFICATION_ID}/{crop.product_id}"
    )


def parse_response(payload: Any, task: Task) -> list[dict[str, str]]:
    """Validate a SIDRA response and return its data rows (header row removed)."""
    if not isinstance(payload, list) or len(payload) < 2:
        raise InvalidResponseError("expected a JSON list with a header row and data rows")

    header, rows = payload[0], payload[1:]
    if tuple(header) != SOURCE_COLUMNS:
        raise InvalidResponseError(f"unexpected columns: {list(header)}")

    for row in rows:
        if tuple(row) != SOURCE_COLUMNS:
            raise InvalidResponseError(f"unexpected columns in row: {list(row)}")
        if row["D3C"] != str(task.year) or row["D4C"] != str(task.crop.product_id):
            raise InvalidResponseError(
                f"row does not match request (year={row['D3C']}, product={row['D4C']})"
            )
    return rows


def to_table(rows: list[dict[str, str]], source_url: str, ingested_at: datetime) -> pa.Table:
    columns = {name: pa.array([row[name] for row in rows], pa.string()) for name in SOURCE_COLUMNS}
    columns["_source_url"] = pa.array([source_url] * len(rows), pa.string())
    columns["_ingested_at"] = pa.array([ingested_at] * len(rows), pa.timestamp("us", tz="UTC"))
    return pa.table(columns)


def partition_path(output_dir: Path, task: Task) -> Path:
    return output_dir / f"crop={task.crop.slug}" / f"year={task.year}" / "data.parquet"


def write_parquet_atomic(table: pa.Table, path: Path) -> None:
    """Write to a temporary file and rename, so an interrupted run never leaves a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".parquet.tmp")
    pq.write_table(table, tmp_path)
    os.replace(tmp_path, path)


def plan_tasks(
    crops: Iterable[Crop], latest_year: int, years: Iterable[int] | None = None
) -> list[Task]:
    wanted = set(years) if years is not None else None
    return [
        Task(crop, year)
        for crop in crops
        for year in range(crop.first_year, latest_year + 1)
        if wanted is None or year in wanted
    ]


def should_download(year: int, latest_year: int, exists: bool, force: bool) -> bool:
    return force or not exists or year > latest_year - REVISED_YEARS


def fetch_latest_year(fetch_json: Callable[[str], Any]) -> int:
    return int(fetch_json(METADATA_URL)["periodicidade"]["fim"])


def run(
    tasks: list[Task],
    fetch_json: Callable[[str], Any],
    output_dir: Path,
    latest_year: int,
    force: bool = False,
) -> dict[str, int]:
    counts = {"downloaded": 0, "skipped": 0, "failed": 0}
    total = len(tasks)

    for i, task in enumerate(tasks, start=1):
        prefix = f"[{i}/{total}] {task.crop.slug} {task.year}"
        path = partition_path(output_dir, task)

        if not should_download(task.year, latest_year, path.exists(), force):
            logger.info("%s: skipped (already exists)", prefix)
            counts["skipped"] += 1
            continue

        url = build_url(task.crop, task.year)
        started = time.monotonic()
        try:
            payload = fetch_json(url)
            ingested_at = datetime.now(UTC)
            rows = parse_response(payload, task)
            write_parquet_atomic(to_table(rows, url, ingested_at), path)
        except Exception:
            logger.exception("%s: failed", prefix)
            counts["failed"] += 1
            continue

        logger.info("%s: %d rows written (%.1fs)", prefix, len(rows), time.monotonic() - started)
        counts["downloaded"] += 1

    return counts


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ingest-pam",
        description="Download IBGE PAM (SIDRA table 5457) into raw Parquet partitions.",
    )
    parser.add_argument(
        "--crops", nargs="+", choices=sorted(CROPS), help="crops to ingest (default: all)"
    )
    parser.add_argument("--years", nargs="+", type=int, help="years to ingest (default: all)")
    parser.add_argument(
        "--force", action="store_true", help="re-download partitions that already exist"
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args = parse_args(argv)
    crops = [CROPS[slug] for slug in args.crops] if args.crops else list(CROPS.values())

    with HttpClient() as client:
        latest_year = fetch_latest_year(client.get_json)
        tasks = plan_tasks(crops, latest_year, args.years)
        logger.info(
            "latest PAM year: %d (years >= %d are always refreshed); %d partitions to check",
            latest_year,
            latest_year - REVISED_YEARS + 1,
            len(tasks),
        )
        if not tasks:
            logger.warning("nothing to do: check --years against each crop's available range")
            return 0
        counts = run(tasks, client.get_json, args.output_dir, latest_year, args.force)

    logger.info("done: %(downloaded)d downloaded, %(skipped)d skipped, %(failed)d failed", counts)
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
