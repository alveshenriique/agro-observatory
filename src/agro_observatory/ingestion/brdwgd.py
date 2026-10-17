"""Aggregate BR-DWGD gridded daily climate to municipality × day and save it as Parquet.

Steps (see README, "Clima: BR-DWGD agregado por município"):
1. download the IBGE municipal mesh and the needed BR-DWGD NetCDF files;
2. map each municipality to grid cells: the 0.1° cells whose center falls inside the polygon,
   or, when none does (small municipalities), the cell containing the polygon's
   representative point (or the nearest cell with data within 0.2°, for coastal ones);
3. for each year, average the cells of each municipality (ignoring missing cells) for
   precipitation, Tmax, Tmin and ETo, and write data/raw/climate/brdwgd_daily/year=Y/.

Unlike the other raw sources, the output is typed (numeric): it is derived from a spatial
aggregation, not a copy of what the source returned.
"""

import argparse
import logging
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pyarrow as pa
import shapely
import xarray as xr
from scipy import sparse
from shapely.geometry import shape

from agro_observatory.ingestion.brdwgd_download import (
    CHECKSUMS_PATH,
    DEFAULT_NETCDF_DIR,
    SOURCE_VERSION,
    download_netcdf_files,
    read_checksums,
    verify_checksum,
)
from agro_observatory.ingestion.common import configure_logging, write_parquet_atomic
from agro_observatory.ingestion.ibge_mesh import DEFAULT_MESH_PATH, download_mesh, read_mesh

logger = logging.getLogger(__name__)

FIRST_YEAR, LAST_YEAR = 1980, 2025
DEFAULT_OUTPUT_DIR = Path("data/raw/climate")
DAILY_DIR = "brdwgd_daily"
CELLS_FILE = "brdwgd_municipality_cells.parquet"

# NetCDF variable -> output column.
VARIABLES = {
    "pr": "precipitation_mm",
    "Tmax": "tmax_c",
    "Tmin": "tmin_c",
    "ETo": "eto_mm",
}

# ~2 cells: a coastal municipality may borrow a neighboring land cell, not a distant one.
MAX_FALLBACK_DISTANCE_DEG = 0.2

FILE_PATTERN = re.compile(r"^(?P<var>[A-Za-z]+)_(?P<start>\d{8})_(?P<end>\d{8})_BR-DWGD")


@dataclass(frozen=True)
class Grid:
    latitudes: np.ndarray
    longitudes: np.ndarray

    @property
    def shape(self) -> tuple[int, int]:
        return len(self.latitudes), len(self.longitudes)

    def cell_index(self, lon: float, lat: float) -> int:
        """Flat index (row-major, lat × lon) of the cell containing a point."""
        row = int(np.abs(self.latitudes - lat).argmin())
        col = int(np.abs(self.longitudes - lon).argmin())
        return row * len(self.longitudes) + col


@dataclass(frozen=True)
class CellMapping:
    municipality_ids: np.ndarray  # (n_municipalities,)
    matrix: sparse.csr_matrix  # (n_municipalities, n_grid_cells), 1 where the cell is used
    methods: list[str]
    representative_points: np.ndarray  # (n_municipalities, 2) lon, lat
    centroids: np.ndarray  # (n_municipalities, 2) lon, lat


def fallback_cell(
    grid: Grid,
    valid: np.ndarray,
    lon_flat: np.ndarray,
    lat_flat: np.ndarray,
    lon: float,
    lat: float,
) -> tuple[np.ndarray, str]:
    """Cell for a municipality with no cell center inside it.

    The cell containing the representative point; if that cell has no data (coastal
    municipalities), the nearest cell with data within MAX_FALLBACK_DISTANCE_DEG; otherwise
    none (the municipality gets no climate data rather than data from somewhere far away).
    """
    cell = grid.cell_index(lon, lat)
    if valid[cell]:
        return np.array([cell]), "representative_point"
    distances = np.hypot(lon_flat - lon, lat_flat - lat)
    distances[~valid] = np.inf
    nearest = int(distances.argmin())
    if distances[nearest] <= MAX_FALLBACK_DISTANCE_DEG:
        return np.array([nearest]), "nearest_valid_cell"
    return np.array([], dtype=int), "no_data"


def map_cells(geometries: dict[int, dict], grid: Grid, valid: np.ndarray) -> CellMapping:
    """Map municipalities to grid cells (see module docstring).

    `valid` is a flat boolean mask of cells that have data; cells without data are never
    used, so a polygon whose inside cells are all missing falls back to its representative
    point too.
    """
    lon_grid, lat_grid = np.meshgrid(grid.longitudes, grid.latitudes)
    lon_flat, lat_flat = lon_grid.ravel(), lat_grid.ravel()

    ids = sorted(geometries)
    rows, cols, methods, points, centroids = [], [], [], [], []
    for i, municipality_id in enumerate(ids):
        polygon = shape(geometries[municipality_id])
        min_lon, min_lat, max_lon, max_lat = polygon.bounds
        candidates = np.flatnonzero(
            valid
            & (lon_flat >= min_lon)
            & (lon_flat <= max_lon)
            & (lat_flat >= min_lat)
            & (lat_flat <= max_lat)
        )
        inside = candidates[
            shapely.contains_xy(polygon, lon_flat[candidates], lat_flat[candidates])
        ]
        point = polygon.representative_point()
        if len(inside):
            cells, method = inside, "cells_inside"
        else:
            cells, method = fallback_cell(grid, valid, lon_flat, lat_flat, point.x, point.y)
        rows.extend([i] * len(cells))
        cols.extend(cells.tolist())
        methods.append(method)
        points.append((point.x, point.y))
        centroids.append((polygon.centroid.x, polygon.centroid.y))

    matrix = sparse.csr_matrix(
        (np.ones(len(rows), dtype=np.float32), (rows, cols)),
        shape=(len(ids), grid.shape[0] * grid.shape[1]),
    )
    return CellMapping(
        np.array(ids, dtype=np.int32), matrix, methods, np.array(points), np.array(centroids)
    )


def municipal_means(mapping: CellMapping, values: np.ndarray) -> np.ndarray:
    """Average each municipality's cells for every day, ignoring missing (NaN) cells.

    `values` has shape (n_days, n_grid_cells); returns (n_municipalities, n_days), NaN where
    all of a municipality's cells are missing that day.
    """
    present = ~np.isnan(values)
    sums = mapping.matrix @ np.where(present, values, 0).T
    counts = mapping.matrix @ present.T.astype(np.float32)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(counts > 0, sums / counts, np.nan).astype(np.float32)


def netcdf_file_for(variable: str, year: int, netcdf_dir: Path) -> Path:
    for path in sorted(netcdf_dir.glob(f"{variable}_*.nc")):
        match = FILE_PATTERN.match(path.name)
        if match and match["var"] == variable:
            if int(match["start"][:4]) <= year <= int(match["end"][:4]):
                return path
    raise FileNotFoundError(f"no BR-DWGD file for {variable} {year} in {netcdf_dir}")


_verified: set[Path] = set()


def verified(path: Path, checksums_path: Path = CHECKSUMS_PATH) -> Path:
    """Check a NetCDF file against the SHA-256 manifest once per run, before reading it.

    Files are hashed only when first read, so a rerun that skips every year hashes nothing
    but the file used to build the grid.
    """
    if path not in _verified:
        verify_checksum(path, read_checksums(checksums_path))
        _verified.add(path)
    return path


def read_year(variable: str, year: int, netcdf_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    """Daily grid for one year: (dates, values with shape (n_days, n_grid_cells))."""
    path = verified(netcdf_file_for(variable, year, netcdf_dir))
    with xr.open_dataset(path) as dataset:
        data = dataset[variable].sel(time=str(year))
        values = data.values.astype(np.float32).reshape(len(data.time), -1)
        return data.time.values.astype("datetime64[D]"), values


def read_grid(netcdf_dir: Path) -> tuple[Grid, np.ndarray]:
    """Grid coordinates and the flat mask of cells with data (from the first day of Tmin)."""
    path = verified(netcdf_file_for("Tmin", LAST_YEAR, netcdf_dir))
    with xr.open_dataset(path) as dataset:
        grid = Grid(dataset.latitude.values, dataset.longitude.values)
        first_day = dataset["Tmin"].isel(time=0).values.ravel()
    return grid, ~np.isnan(first_day)


def cells_table(mapping: CellMapping, ingested_at: datetime) -> pa.Table:
    counts = np.diff(mapping.matrix.indptr).astype(np.int32)
    n = len(mapping.municipality_ids)
    return pa.table(
        {
            "municipality_id": pa.array(mapping.municipality_ids, pa.int32()),
            "method": pa.array(mapping.methods, pa.string()),
            "cell_count": pa.array(counts, pa.int32()),
            "representative_lon": pa.array(mapping.representative_points[:, 0], pa.float64()),
            "representative_lat": pa.array(mapping.representative_points[:, 1], pa.float64()),
            "centroid_lon": pa.array(mapping.centroids[:, 0], pa.float64()),
            "centroid_lat": pa.array(mapping.centroids[:, 1], pa.float64()),
            "_source_version": pa.array([SOURCE_VERSION] * n, pa.string()),
            "_ingested_at": pa.array([ingested_at] * n, pa.timestamp("us", tz="UTC")),
        }
    )


def daily_table(
    mapping: CellMapping, dates: np.ndarray, means: dict[str, np.ndarray], ingested_at: datetime
) -> pa.Table:
    n_municipalities, n_days = len(mapping.municipality_ids), len(dates)
    columns = {
        "municipality_id": pa.array(np.repeat(mapping.municipality_ids, n_days), pa.int32()),
        "date": pa.array(np.tile(dates, n_municipalities), pa.date32()),
    }
    for column, values in means.items():
        columns[column] = pa.array(values.ravel(), pa.float32(), from_pandas=True)
    rows = n_municipalities * n_days
    columns["_source_version"] = pa.array([SOURCE_VERSION] * rows, pa.string())
    columns["_ingested_at"] = pa.array([ingested_at] * rows, pa.timestamp("us", tz="UTC"))
    return pa.table(columns)


def year_path(output_dir: Path, year: int) -> Path:
    return output_dir / DAILY_DIR / f"year={year}" / "data.parquet"


def load_or_build_mapping(
    mesh_path: Path, netcdf_dir: Path, output_dir: Path, force: bool
) -> CellMapping:
    grid, valid = read_grid(netcdf_dir)
    mapping = map_cells(read_mesh(mesh_path), grid, valid)
    cells_path = output_dir / CELLS_FILE
    if force or not cells_path.exists():
        write_parquet_atomic(cells_table(mapping, datetime.now(UTC)), cells_path)
    methods = {m: mapping.methods.count(m) for m in sorted(set(mapping.methods))}
    logger.info("cell mapping: %d municipalities, by method %s", len(mapping.methods), methods)
    return mapping


def aggregate_years(
    mapping: CellMapping, years: list[int], netcdf_dir: Path, output_dir: Path, force: bool
) -> None:
    for year in years:
        path = year_path(output_dir, year)
        if path.exists() and not force:
            logger.info("%d: skipped (already exists)", year)
            continue
        started = datetime.now(UTC)
        means, dates = {}, None
        for variable, column in VARIABLES.items():
            variable_dates, values = read_year(variable, year, netcdf_dir)
            if dates is not None and not np.array_equal(dates, variable_dates):
                raise ValueError(f"{year}: dates differ between variables")
            dates = variable_dates
            means[column] = municipal_means(mapping, values)
        table = daily_table(mapping, dates, means, datetime.now(UTC))
        write_parquet_atomic(table, path)
        seconds = (datetime.now(UTC) - started).total_seconds()
        logger.info("%d: %d rows written (%.1fs)", year, table.num_rows, seconds)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="ingest-brdwgd",
        description="Aggregate BR-DWGD daily climate to municipalities (Parquet by year).",
    )
    parser.add_argument("--years", nargs="+", type=int, help=f"default: {FIRST_YEAR}-{LAST_YEAR}")
    parser.add_argument("--force", action="store_true", help="rebuild existing years")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--netcdf-dir", type=Path, default=DEFAULT_NETCDF_DIR)
    parser.add_argument("--mesh-path", type=Path, default=DEFAULT_MESH_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    years = args.years or list(range(FIRST_YEAR, LAST_YEAR + 1))
    if not all(FIRST_YEAR <= y <= LAST_YEAR for y in years):
        parser.error(f"years must be within {FIRST_YEAR}-{LAST_YEAR}")

    if not args.skip_download:
        download_mesh(args.mesh_path)
        download_netcdf_files(args.netcdf_dir)
    mapping = load_or_build_mapping(args.mesh_path, args.netcdf_dir, args.output_dir, args.force)
    aggregate_years(mapping, years, args.netcdf_dir, args.output_dir, args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
