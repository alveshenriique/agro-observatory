import io
import json
import zipfile
from datetime import UTC, datetime

import httpx
import numpy as np
import pytest

from agro_observatory.ingestion import brdwgd
from agro_observatory.ingestion.brdwgd_download import (
    ChecksumError,
    HttpRangeFile,
    is_needed,
    read_checksums,
    sha256_file,
    verify_checksum,
)
from agro_observatory.ingestion.ibge_mesh import read_mesh

# 3 x 4 grid of 1-degree cells, centers at lat 0..2 and lon 10..13.
GRID = brdwgd.Grid(latitudes=np.array([0.0, 1.0, 2.0]), longitudes=np.array([10.0, 11, 12, 13]))
ALL_VALID = np.ones(12, dtype=bool)


def square(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> dict:
    ring = [
        [min_lon, min_lat],
        [max_lon, min_lat],
        [max_lon, max_lat],
        [min_lon, max_lat],
        [min_lon, min_lat],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def test_map_cells_uses_cells_inside_or_the_representative_point() -> None:
    geometries = {
        1: square(9.5, -0.5, 11.5, 0.5),  # contains cell centers (0, 10) and (0, 11)
        2: square(12.2, 1.2, 12.4, 1.4),  # too small: no center inside
    }

    mapping = brdwgd.map_cells(geometries, GRID, ALL_VALID)

    assert mapping.municipality_ids.tolist() == [1, 2]
    assert mapping.methods == ["cells_inside", "representative_point"]
    assert mapping.matrix[0].indices.tolist() == [0, 1]
    # Representative point (~12.3, 1.3) falls in the cell centered at (12, 1): row 1, col 2.
    assert mapping.matrix[1].indices.tolist() == [1 * 4 + 2]


def test_map_cells_ignores_cells_without_data() -> None:
    valid = ALL_VALID.copy()
    valid[0] = False  # cell (0, 10) has no data

    mapping = brdwgd.map_cells({1: square(9.5, -0.5, 11.5, 0.5)}, GRID, valid)

    assert mapping.matrix[0].indices.tolist() == [1]


def test_municipal_means_ignore_missing_cells() -> None:
    mapping = brdwgd.map_cells({1: square(9.5, -0.5, 11.5, 0.5)}, GRID, ALL_VALID)
    values = np.full((2, 12), np.nan, dtype=np.float32)
    values[0, 0], values[0, 1] = 10.0, 20.0  # day 1: both cells
    values[1, 1] = 30.0  # day 2: only one cell has data

    means = brdwgd.municipal_means(mapping, values)

    assert means.shape == (1, 2)
    assert means[0].tolist() == [15.0, 30.0]


def test_municipal_means_are_nan_when_all_cells_are_missing() -> None:
    mapping = brdwgd.map_cells({1: square(9.5, -0.5, 11.5, 0.5)}, GRID, ALL_VALID)

    means = brdwgd.municipal_means(mapping, np.full((1, 12), np.nan, dtype=np.float32))

    assert np.isnan(means[0, 0])


def test_netcdf_file_for_picks_the_period(tmp_path) -> None:
    for name in (
        "pr_19610101_19801231_BR-DWGD_UFES_UTEXAS_v_3.2.4.nc",
        "pr_19810101_20001231_BR-DWGD_UFES_UTEXAS_v_3.2.4.nc",
        "pr_Control_19610101_19801231_BR-DWGD_UFES_UTEXAS_v_3.2.4.nc",
    ):
        (tmp_path / name).touch()

    assert brdwgd.netcdf_file_for("pr", 1980, tmp_path).name.startswith("pr_19610101")
    assert brdwgd.netcdf_file_for("pr", 1981, tmp_path).name.startswith("pr_19810101")
    with pytest.raises(FileNotFoundError):
        brdwgd.netcdf_file_for("pr", 2001, tmp_path)


def test_daily_table_is_municipality_by_day() -> None:
    mapping = brdwgd.map_cells({7: square(9.5, -0.5, 11.5, 0.5)}, GRID, ALL_VALID)
    dates = np.array(["2025-01-01", "2025-01-02"], dtype="datetime64[D]")
    means = {"precipitation_mm": np.array([[1.5, np.nan]], dtype=np.float32)}

    table = brdwgd.daily_table(mapping, dates, means, datetime(2026, 1, 1, tzinfo=UTC))

    rows = table.select(["municipality_id", "date", "precipitation_mm"]).to_pylist()
    assert [(r["municipality_id"], str(r["date"]), r["precipitation_mm"]) for r in rows] == [
        (7, "2025-01-01", 1.5),
        (7, "2025-01-02", None),
    ]


def test_is_needed_selects_only_the_four_variables() -> None:
    assert is_needed("pr_20010101_20251231_BR-DWGD_UFES_UTEXAS_v_3.2.4.nc")
    assert is_needed("folder/ETo_19810101_20001231_BR-DWGD_UFES_UTEXAS_v_3.2.4.nc")
    assert not is_needed("Rs_20010101_20251231_BR-DWGD_UFES_UTEXAS_v_3.2.4.nc")
    assert not is_needed("u2_20010101_20251231_BR-DWGD_UFES_UTEXAS_v_3.2.4.nc")


def test_http_range_file_reads_zip_members_without_downloading_everything() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("pr_x.nc", b"precipitation" * 100)
        # Incompressible and large: the test checks it is never downloaded.
        archive.writestr("Rs_x.nc", np.random.default_rng(0).bytes(50_000))
    payload = buffer.getvalue()
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        start, end = map(int, request.headers["Range"].removeprefix("bytes=").split("-"))
        requested.append(request.headers["Range"])
        headers = {"Content-Range": f"bytes {start}-{end}/{len(payload)}"}
        return httpx.Response(206, content=payload[start : end + 1], headers=headers)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        remote = io.BufferedReader(HttpRangeFile(client, "http://example/x.zip"), 256)
        with zipfile.ZipFile(remote) as archive:
            assert archive.read("pr_x.nc") == b"precipitation" * 100

    downloaded = 0
    for header in requested:
        start, end = map(int, header.removeprefix("bytes=").split("-"))
        downloaded += end - start + 1
    assert downloaded < len(payload) / 10


def test_fallback_uses_nearest_valid_cell_close_by_or_nothing() -> None:
    valid = ALL_VALID.copy()
    valid[1 * 4 + 2] = False  # the cell containing the small polygon has no data (sea)
    small = square(12.2, 1.2, 12.4, 1.4)

    near = brdwgd.map_cells({1: small}, GRID, valid)
    assert near.methods == ["no_data"]  # nearest valid cell is 0.7 degrees away

    fine_grid = brdwgd.Grid(np.array([1.2, 1.3]), np.array([12.2, 12.4]))
    fine_valid = np.array([True, True, True, False])
    coastal = brdwgd.map_cells({1: square(12.35, 1.25, 12.37, 1.27)}, fine_grid, fine_valid)
    assert coastal.methods == ["nearest_valid_cell"]


def test_read_mesh_indexes_geometries_by_municipality_id(tmp_path) -> None:
    path = tmp_path / "mesh.geojson"
    feature = {
        "type": "Feature",
        "properties": {"codarea": "5107925"},
        "geometry": square(0, 0, 1, 1),
    }
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}))

    assert read_mesh(path) == {5107925: square(0, 0, 1, 1)}


def test_checksums_accept_the_manifest_and_reject_changed_or_unknown_files(tmp_path) -> None:
    good = tmp_path / "pr_x.nc"
    good.write_bytes(b"grid")
    manifest = tmp_path / "manifest.sha256"
    manifest.write_text(f"{sha256_file(good)}  pr_x.nc\n")
    checksums = read_checksums(manifest)

    verify_checksum(good, checksums)  # does not raise

    good.write_bytes(b"changed grid")
    with pytest.raises(ChecksumError, match="does not match"):
        verify_checksum(good, checksums)
    with pytest.raises(ChecksumError, match="not in the checksum manifest"):
        verify_checksum(tmp_path / "Tmax_x.nc", checksums)


def test_checksum_manifest_covers_every_needed_file() -> None:
    checksums = read_checksums()

    assert len(checksums) == 12
    assert {name.split("_")[0] for name in checksums} == {"pr", "Tmax", "Tmin", "ETo"}
    assert all(len(digest) == 64 for digest in checksums.values())
