"""A small TopoJSON encoder and decoder for polygon coverages (municipal meshes).

TopoJSON stores each shared boundary once, as an "arc", and every polygon ring as a list of
arc indices (a negative index ~i means arc i reversed). Coordinates are quantized to an
integer grid and delta-encoded, which makes the file much smaller than GeoJSON. Because two
neighbours reference the same arc, their common border is identical by construction: no gaps
or overlaps appear between them, whatever the simplification.

The encoder expects a valid coverage (polygons that only touch along shared edges, with the
same vertices on both sides), as produced by shapely.coverage_simplify. Steps:
1. quantize every ring to the grid, drop repeated points and spikes (A, B, A);
2. find the junctions: points with more than two distinct neighbours, where a boundary
   between two polygons starts or ends, or points a ring visits twice;
3. cut each ring at its junctions into arcs (a ring without junctions is a single closed arc,
   rotated to start at its smallest point, so an enclave and its container's hole match);
4. store each arc once, whatever the direction it is traversed in.
Exterior rings are clockwise and holes counter-clockwise, the winding d3-geo expects.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence

import shapely
from shapely.geometry import MultiPolygon, Polygon

Point = tuple[int, int]


def _signed_area(ring: Sequence[Point]) -> float:
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:], strict=False)) / 2


def _clean_ring(ring: list[Point]) -> list[Point] | None:
    """Closed ring without repeated points or spikes; None if it collapsed on the grid."""
    pts = [p for i, p in enumerate(ring) if i == 0 or p != ring[i - 1]]
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    changed = True
    while changed and len(pts) > 3:
        changed = False
        core = pts[:-1]
        n = len(core)
        for i in range(n):
            if core[(i - 1) % n] == core[(i + 1) % n]:  # spike A, B, A: drop B and one A
                drop = {i, (i + 1) % n}
                core = [p for j, p in enumerate(core) if j not in drop]
                changed = True
                break
        pts = core + [core[0]] if core else []
    if len(pts) < 4 or _signed_area(pts) == 0:
        return None
    return pts


def _polygons(geometry) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    raise TypeError(f"expected Polygon or MultiPolygon, got {geometry.geom_type}")


class Quantizer:
    def __init__(self, bbox: Sequence[float], quantization: int):
        x0, y0, x1, y1 = bbox
        self.x0, self.y0 = x0, y0
        self.kx = (quantization - 1) / (x1 - x0) if x1 > x0 else 1.0
        self.ky = (quantization - 1) / (y1 - y0) if y1 > y0 else 1.0

    def __call__(self, coords: Iterable[Sequence[float]]) -> list[Point]:
        return [(round((x - self.x0) * self.kx), round((y - self.y0) * self.ky)) for x, y in coords]

    @property
    def transform(self) -> dict:
        return {"scale": [1 / self.kx, 1 / self.ky], "translate": [self.x0, self.y0]}


def encode(
    objects: dict[str, Sequence[tuple[int, Polygon | MultiPolygon]]],
    quantization: int,
    bbox: Sequence[float] | None = None,
) -> dict:
    """TopoJSON Topology with one GeometryCollection per object name.

    `objects` maps an object name to (id, geometry) pairs. Raises ValueError if a geometry
    vanishes on the grid (every ring collapsed). Rounding to the grid can make a ring cross
    itself where two parts of a boundary are closer than one cell: snap the coverage to the
    grid first (mesh.snap_coverage) and pass the same `bbox`.
    """
    geometries = [g for items in objects.values() for _, g in items]
    if bbox is None:
        bbox = [float(v) for v in shapely.total_bounds(geometries)]
    quantize = Quantizer(bbox, quantization)

    # 1. Quantized, cleaned, correctly wound rings, grouped by object > geometry > polygon.
    shapes: dict[str, list[tuple[int, list[list[list[Point]]]]]] = {}
    rings: list[list[Point]] = []
    for name, items in objects.items():
        out = []
        for gid, geometry in items:
            polygons = []
            for polygon in _polygons(geometry):
                exterior = _clean_ring(quantize(polygon.exterior.coords))
                if exterior is None:
                    continue
                if _signed_area(exterior) > 0:  # clockwise exterior
                    exterior.reverse()
                polygon_rings = [exterior]
                for interior in polygon.interiors:
                    hole = _clean_ring(quantize(interior.coords))
                    if hole is None:
                        continue
                    if _signed_area(hole) < 0:  # counter-clockwise hole
                        hole.reverse()
                    polygon_rings.append(hole)
                rings.extend(polygon_rings)
                polygons.append(polygon_rings)
            if not polygons:
                raise ValueError(
                    f"geometry {gid} of {name!r} vanished at quantization {quantization}"
                )
            out.append((gid, polygons))
        shapes[name] = out

    # 2. Junctions.
    neighbours: dict[Point, set[Point]] = defaultdict(set)
    junctions: set[Point] = set()
    for ring in rings:
        core = ring[:-1]
        n = len(core)
        seen: set[Point] = set()
        for i, p in enumerate(core):
            neighbours[p].add(core[(i - 1) % n])
            neighbours[p].add(core[(i + 1) % n])
            if p in seen:
                junctions.add(p)
            seen.add(p)
    junctions.update(p for p, ns in neighbours.items() if len(ns) != 2)

    # 3-4. Cut rings into arcs and store each arc once.
    arcs: list[list[Point]] = []
    index: dict[tuple[Point, ...], int] = {}

    def arc_id(points: list[Point]) -> int:
        key = tuple(points)
        if key in index:
            return index[key]
        reverse = key[::-1]
        if reverse in index:
            return ~index[reverse]
        index[key] = len(arcs)
        arcs.append(points)
        return index[key]

    def ring_arcs(ring: list[Point]) -> list[int]:
        core = ring[:-1]
        cuts = [i for i, p in enumerate(core) if p in junctions]
        if not cuts:
            start = core.index(min(core))
            loop = core[start:] + core[:start]
            loop.append(loop[0])
            key = tuple(loop)
            reverse = key[::-1]
            # A closed loop traversed the other way starts at the same smallest point.
            if reverse in index:
                return [~index[reverse]]
            return [arc_id(loop)]
        rotated = core[cuts[0] :] + core[: cuts[0]]
        cuts = [i - cuts[0] for i in cuts]
        cuts.append(len(rotated))
        rotated.append(rotated[0])
        return [arc_id(rotated[a : b + 1]) for a, b in zip(cuts, cuts[1:], strict=False)]

    topology_objects = {}
    for name, items in shapes.items():
        geometries_out = []
        for gid, polygons in items:
            arcs_of = [[ring_arcs(ring) for ring in polygon] for polygon in polygons]
            if len(arcs_of) == 1:
                geometries_out.append({"type": "Polygon", "id": gid, "arcs": arcs_of[0]})
            else:
                geometries_out.append({"type": "MultiPolygon", "id": gid, "arcs": arcs_of})
        topology_objects[name] = {"type": "GeometryCollection", "geometries": geometries_out}

    encoded = []
    for arc in arcs:
        deltas = [list(arc[0])]
        deltas.extend([b[0] - a[0], b[1] - a[1]] for a, b in zip(arc, arc[1:], strict=False))
        encoded.append(deltas)
    return {
        "type": "Topology",
        "bbox": bbox,
        "transform": quantize.transform,
        "objects": topology_objects,
        "arcs": encoded,
    }


def _decoded_arcs(topology: dict) -> list[list[Point]]:
    out = []
    for arc in topology["arcs"]:
        x = y = 0
        points = []
        for dx, dy in arc:
            x += dx
            y += dy
            points.append((x, y))
        out.append(points)
    return out


def decode(topology: dict, name: str, quantized: bool = False) -> list[tuple[int, MultiPolygon]]:
    """(id, MultiPolygon) for every geometry of an object, in grid units if `quantized`."""
    arcs = _decoded_arcs(topology)
    scale, translate = topology["transform"]["scale"], topology["transform"]["translate"]

    def ring(indices: list[int]) -> list[tuple[float, float]]:
        points: list[Point] = []
        for i in indices:
            arc = arcs[i] if i >= 0 else arcs[~i][::-1]
            points.extend(arc if not points else arc[1:])
        if quantized:
            return [(float(x), float(y)) for x, y in points]
        return [(x * scale[0] + translate[0], y * scale[1] + translate[1]) for x, y in points]

    out = []
    for geometry in topology["objects"][name]["geometries"]:
        polygons = geometry["arcs"] if geometry["type"] == "MultiPolygon" else [geometry["arcs"]]
        out.append(
            (
                geometry["id"],
                MultiPolygon([Polygon(ring(p[0]), [ring(h) for h in p[1:]]) for p in polygons]),
            )
        )
    return out


def exterior_rings_are_clockwise(geometry: MultiPolygon) -> bool:
    """d3-geo winding: exterior rings clockwise, holes counter-clockwise."""
    return all(not p.exterior.is_ccw and all(i.is_ccw for i in p.interiors) for p in geometry.geoms)
