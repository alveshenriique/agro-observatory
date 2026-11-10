"""Web mesh: the IBGE municipal mesh simplified as a coverage and encoded as TopoJSON.

Source: data/raw/ibge_mesh/municipalities.geojson (maximum quality, about 3 million vertices).
1. Resolve overlaps between neighbours: the maximum-quality mesh has one, about 1,200 m2
   between Fortaleza and Caucaia (CE). The overlapping area stays with the municipality with
   the smaller code. Any other coverage problem (a gap) stops the export.
2. Simplify the whole coverage with shapely.coverage_simplify (Visvalingam-Whyatt applied to
   the shared edges, once per edge), so neighbours keep an identical border.
3. Snap the simplified coverage to the integer grid of the TopoJSON file (snap_coverage).
   Rounding each vertex separately makes a ring cross itself wherever two parts of a boundary
   are closer than one grid cell (narrow strips, islands); snapping the whole linework at
   once and rebuilding the faces keeps every polygon valid and every border shared.
4. Encode as TopoJSON (topojson.py): the national map (tolerance 0.025 degrees, grid of
   10,000 x 10,000, about 290 KiB with gzip, within the Explorar page budget), the state
   outlines (dissolved from the municipal coverage at 0.04 degrees) and one detailed file per
   state (0.005 degrees, grid of 100,000).
The tolerance is the square root of the area of the triangles removed, in degrees.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import shape

from atlas_da_lavoura.serving import topojson

logger = logging.getLogger(__name__)

DEFAULT_MESH = Path("data/raw/ibge_mesh/municipalities.geojson")


@dataclass(frozen=True)
class Level:
    name: str
    tolerance: float
    quantization: int


NATIONAL = Level("national", 0.025, 10_000)
STATE_OUTLINES = Level("state_outlines", 0.04, 10_000)
STATE_DETAIL = Level("state_detail", 0.005, 100_000)


def load_mesh(path: Path) -> tuple[list[int], np.ndarray]:
    """Municipality ids (ascending) and their geometries."""
    features = json.loads(path.read_text(encoding="utf-8"))["features"]
    pairs = sorted((int(f["properties"]["codarea"]), shape(f["geometry"])) for f in features)
    ids = [i for i, _ in pairs]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{path}: repeated municipality codes")
    return ids, np.array([g for _, g in pairs], dtype=object)


def resolve_overlaps(ids: list[int], geometries: np.ndarray) -> tuple[np.ndarray, list[dict]]:
    """Remove overlaps between municipalities (kept by the smaller code); fail on anything else."""
    geometries = geometries.copy()
    fixes = []
    invalid = shapely.coverage_invalid_edges(geometries)
    candidates = [i for i, edges in enumerate(invalid) if not edges.is_empty]
    if candidates:
        tree = shapely.STRtree(geometries)
        for i in candidates:
            for j in tree.query(geometries[i], predicate="intersects"):
                if j <= i:
                    continue
                overlap = geometries[i].intersection(geometries[j])
                if overlap.area > 0:
                    # j has the larger code (ids are sorted): it gives up the overlap.
                    geometries[j] = geometries[j].difference(geometries[i])
                    fixes.append(
                        {
                            "kept_by": ids[i],
                            "removed_from": ids[j],
                            "area_m2": round(
                                overlap.area
                                * 111_320**2
                                * math.cos(math.radians(overlap.centroid.y))
                            ),
                        }
                    )
    if not shapely.coverage_is_valid(geometries):
        bad = [
            ids[i]
            for i, e in enumerate(shapely.coverage_invalid_edges(geometries))
            if not e.is_empty
        ]
        raise ValueError(f"mesh is not a valid coverage after resolving overlaps: {bad[:20]}")
    return geometries, fixes


def snap_coverage(
    ids: list[int], geometries: np.ndarray, bbox: list[float], quantization: int
) -> np.ndarray:
    """The coverage snapped to the TopoJSON grid as a valid coverage (snap rounding).

    1. Move to grid units and merge every boundary into one linework (shared edges once).
    2. Snap-round it to the integer grid (OverlayNG union with grid size 1 nodes the crossings).
    3. Rebuild the faces (polygonize) and give each face to the polygon it overlaps the most;
       faces outside every polygon (gaps such as some lagoons) are dropped.
    4. Each polygon is the union of its faces, back in degrees, exactly on the grid points.
    The faces partition the plane, so neighbours cannot overlap and share identical borders.
    """
    q = topojson.Quantizer(bbox, quantization)

    def to_grid(c):
        return np.column_stack(((c[:, 0] - q.x0) * q.kx, (c[:, 1] - q.y0) * q.ky))

    def from_grid(c):
        return np.column_stack((c[:, 0] / q.kx + q.x0, c[:, 1] / q.ky + q.y0))

    grid = shapely.transform(geometries, to_grid)
    # OverlayNG union at grid size 1: snap rounding, so the linework is noded on the grid.
    lines = shapely.union_all(shapely.boundary(grid), grid_size=1.0)
    faces = shapely.get_parts(shapely.polygonize(shapely.get_parts(lines)))
    tree = shapely.STRtree(grid)
    owned: dict[int, list] = {}
    for face in faces:
        candidates = tree.query(face, predicate="intersects")
        if len(candidates) == 0:
            continue
        # Fixed-precision overlay (OverlayNG): robust for a face that is already on the grid.
        areas = shapely.area(shapely.intersection(face, grid[candidates], grid_size=1e-3))
        best = int(np.argmax(areas))
        if areas[best] > 0:
            owned.setdefault(int(candidates[best]), []).append(face)
    missing = [ids[i] for i in range(len(grid)) if i not in owned]
    if missing:
        raise ValueError(f"municipalities vanished on the {quantization} grid: {missing[:20]}")
    snapped = [
        owned[i][0] if len(owned[i]) == 1 else shapely.coverage_union_all(owned[i])
        for i in range(len(grid))
    ]
    return shapely.transform(np.array(snapped, dtype=object), from_grid)


def _encode_coverage(name: str, ids: list[int], geometries: np.ndarray, quantization: int) -> dict:
    bbox = [float(v) for v in shapely.total_bounds(geometries)]
    snapped = snap_coverage(ids, geometries, bbox, quantization)
    return topojson.encode({name: list(zip(ids, snapped, strict=True))}, quantization, bbox)


def _area_errors(simplified: np.ndarray, original: np.ndarray) -> dict:
    error = np.abs(shapely.area(simplified) - shapely.area(original)) / shapely.area(original)
    return {
        "median": round(float(np.median(error)), 4),
        "p99": round(float(np.quantile(error, 0.99)), 4),
        "max": round(float(error.max()), 4),
    }


def build(mesh_path: Path, states: dict[int, str]) -> tuple[dict[str, dict], dict]:
    """TopoJSON topologies by published path, and statistics for the manifest.

    `states` maps the 2-digit state code to its abbreviation (file names of the state files).
    """
    ids, original = load_mesh(mesh_path)
    geometries, fixes = resolve_overlaps(ids, original)
    vertices = int(shapely.get_num_coordinates(original).sum())
    logger.info(
        "mesh: %d municipalities, %d vertices, %d overlap(s) resolved",
        len(ids),
        vertices,
        len(fixes),
    )

    files: dict[str, dict] = {}
    stats: dict = {"source_vertices": vertices, "overlaps_resolved": fixes, "levels": {}}

    national = shapely.coverage_simplify(geometries, NATIONAL.tolerance)
    files["geo/municipalities.topo.json"] = _encode_coverage(
        "municipalities", ids, national, NATIONAL.quantization
    )
    stats["levels"][NATIONAL.name] = {
        "tolerance_degrees": NATIONAL.tolerance,
        "quantization": NATIONAL.quantization,
        "area_error": _area_errors(national, original),
    }

    coarse = shapely.coverage_simplify(geometries, STATE_OUTLINES.tolerance)
    by_state: dict[int, list] = {}
    for municipality_id, geometry in zip(ids, coarse, strict=True):
        by_state.setdefault(municipality_id // 100_000, []).append(geometry)
    codes = sorted(by_state)
    outlines = np.array([shapely.coverage_union_all(by_state[c]) for c in codes], dtype=object)
    files["geo/states.topo.json"] = _encode_coverage(
        "states", codes, outlines, STATE_OUTLINES.quantization
    )
    stats["levels"][STATE_OUTLINES.name] = {
        "tolerance_degrees": STATE_OUTLINES.tolerance,
        "quantization": STATE_OUTLINES.quantization,
    }

    detail = shapely.coverage_simplify(geometries, STATE_DETAIL.tolerance)
    for code in codes:
        members = [k for k, i in enumerate(ids) if i // 100_000 == code]
        files[f"geo/state/{states[code]}.topo.json"] = _encode_coverage(
            "municipalities", [ids[k] for k in members], detail[members], STATE_DETAIL.quantization
        )
    stats["levels"][STATE_DETAIL.name] = {
        "tolerance_degrees": STATE_DETAIL.tolerance,
        "quantization": STATE_DETAIL.quantization,
        "area_error": _area_errors(detail, original),
    }
    stats["municipality_ids"] = ids
    return files, stats
