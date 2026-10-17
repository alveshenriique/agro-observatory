"""Build the raw data sample used by CI from the real raw layer.

Reads data/raw/ (produced by the ingestion commands) and writes tests/fixtures/raw/ with the
same layout and schema, so CI can run the real loader and the full dbt build on it:
- PAM: every crop and year, only for the municipalities in SAMPLE_MUNICIPALITIES;
- localities and IPCA: complete (they are small);
- climate (BR-DWGD by municipality): SAMPLE_CLIMATE_YEARS for the same municipalities, and
  their rows of the cell mapping.

Usage: uv run python scripts/make_ci_sample.py [--parts pam snapshots climate]
Regenerating a part rewrites its files even if only `_ingested_at` changed, so regenerate
only the parts whose source actually changed.
"""

import argparse
import shutil
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from agro_observatory.ingestion.common import write_parquet_atomic

SOURCE_DIR = Path("data/raw")
OUTPUT_DIR = Path("tests/fixtures/raw")

# Chosen to cover the cases the models must handle (see README, "CI com amostra dos dados").
SAMPLE_MUNICIPALITIES = {
    "5107925": "Sorriso-MT: large soybean/corn producer, created in 1986",
    "3148103": "Patrocínio-MG: largest arabica producer in MG (biennial cycle)",
    "5101837": "Boa Esperança do Norte-MT: no microregion, data only from 2025",
    "3503505": "Areias-SP: one of the 28 yields published as '-' in 1998",
    "4104808": "Cascavel-PR: South, soybean/corn since 1974",
    "2919553": "Luís Eduardo Magalhães-BA: Northeast frontier, split off in 2000",
    "1100049": "Cacoal-RO: North, coffee canephora",
}
# Consecutive years, so crop windows that cross the turn of the year can be built.
SAMPLE_CLIMATE_YEARS = (2023, 2024, 2025)

PARTS = ("pam", "snapshots", "climate")


def sample_filter(table: pa.Table, column: str, as_int: bool = False) -> pa.Table:
    ids = [int(i) for i in SAMPLE_MUNICIPALITIES] if as_int else list(SAMPLE_MUNICIPALITIES)
    value_set = pa.array(ids, table.schema.field(column).type)
    return table.filter(pc.is_in(table[column], value_set=value_set))


def make_pam() -> str:
    pam_files = sorted(SOURCE_DIR.glob("pam/crop=*/year=*/data.parquet"))
    if not pam_files:
        raise FileNotFoundError(f"no PAM files under {SOURCE_DIR}; run the ingestion first")
    shutil.rmtree(OUTPUT_DIR / "pam", ignore_errors=True)
    rows = 0
    for path in pam_files:
        sample = sample_filter(pq.read_table(path), "D1C")
        write_parquet_atomic(sample, OUTPUT_DIR / path.relative_to(SOURCE_DIR))
        rows += sample.num_rows
    return f"PAM: {len(pam_files)} partitions, {rows} rows"


def make_snapshots() -> str:
    for snapshot in ("localities/municipalities.parquet", "ipca/ipca.parquet"):
        write_parquet_atomic(pq.read_table(SOURCE_DIR / snapshot), OUTPUT_DIR / snapshot)
    return "localities and IPCA copied"


def make_climate() -> str:
    shutil.rmtree(OUTPUT_DIR / "climate", ignore_errors=True)
    cells = "climate/brdwgd_municipality_cells.parquet"
    write_parquet_atomic(
        sample_filter(pq.read_table(SOURCE_DIR / cells), "municipality_id", as_int=True),
        OUTPUT_DIR / cells,
    )
    rows = 0
    for year in SAMPLE_CLIMATE_YEARS:
        relative = f"climate/brdwgd_daily/year={year}/data.parquet"
        sample = sample_filter(pq.read_table(SOURCE_DIR / relative), "municipality_id", True)
        write_parquet_atomic(sample, OUTPUT_DIR / relative)
        rows += sample.num_rows
    return f"climate: {len(SAMPLE_CLIMATE_YEARS)} years, {rows} daily rows"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the CI raw data sample.")
    parser.add_argument("--parts", nargs="+", choices=PARTS, default=list(PARTS))
    args = parser.parse_args(argv)

    builders = {"pam": make_pam, "snapshots": make_snapshots, "climate": make_climate}
    try:
        for part in args.parts:
            print(builders[part]())
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
