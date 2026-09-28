"""Build the raw data sample used by CI from the real raw layer.

Reads data/raw/ (produced by the ingestion commands) and writes tests/fixtures/raw/ with the
same layout and schema, so CI can run the real loader and the full dbt build on it:
- PAM: every crop and year, only for the municipalities in SAMPLE_MUNICIPALITIES;
- localities and IPCA: complete (they are small).

Usage: uv run python scripts/make_ci_sample.py
"""

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


def main() -> int:
    pam_files = sorted(SOURCE_DIR.glob("pam/crop=*/year=*/data.parquet"))
    if not pam_files:
        print(f"no PAM files under {SOURCE_DIR}; run the ingestion first", file=sys.stderr)
        return 1

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)

    municipality_ids = list(SAMPLE_MUNICIPALITIES)
    pam_rows = 0
    for path in pam_files:
        table = pq.read_table(path)
        sample = table.filter(pc.is_in(table["D1C"], value_set=pa.array(municipality_ids)))
        write_parquet_atomic(sample, OUTPUT_DIR / path.relative_to(SOURCE_DIR))
        pam_rows += sample.num_rows

    for snapshot in ("localities/municipalities.parquet", "ipca/ipca.parquet"):
        write_parquet_atomic(pq.read_table(SOURCE_DIR / snapshot), OUTPUT_DIR / snapshot)

    print(f"PAM: {len(pam_files)} partitions, {pam_rows} rows; localities and IPCA copied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
