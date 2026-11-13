// Geometry of the Explorar map, decoded straight from the TopoJSON of the data package.
// Each arc is projected once (the borders shared by two municipalities are stored once, so
// they are projected once too), into fixed map units: x to the right, y down, the extent
// 1,000 units wide. The page then fits the map to any size with an affine transform, so a
// resize never projects again. There is no adaptive resampling: the mesh is already
// simplified for the screen (serving/mesh.py), and resampling the 5,571 polygons three
// times (fit, draw, centroid) is what made d3's geoPath take a third of a second here.
//
// The projection is SIRGAS 2000 / Brazil Albers (EPSG:10857), IBGE's equal-area conic for
// the whole country: standard parallels −2° and −22°, central meridian −54°. The raw
// formula is d3's (geoConicEqualAreaRaw); tests/geometry.test.ts checks it against
// d3.geoConicEqualArea with the same parameters. This module has no DOM: the build uses it
// for the map's aspect ratio.
import { geoConicEqualAreaRaw } from "d3-geo";
import type { GeoTopoJson } from "../../types/data/topology";

const RAD = Math.PI / 180;
export const PARALLELS = [-2, -22] as const;
export const CENTRAL_MERIDIAN = -54;
const raw = geoConicEqualAreaRaw(PARALLELS[0] * RAD, PARALLELS[1] * RAD);

/** Albers coordinates (y down) of a longitude and latitude in degrees. */
export function project(lon: number, lat: number): [number, number] {
  const [x, y] = raw((lon - CENTRAL_MERIDIAN) * RAD, lat * RAD);
  return [x, -y];
}

export const MAP_WIDTH = 1000;
/** Margin around the map, in map units, on every side (the canvas and the SVG share it). */
export const MAP_PAD = 20;

/** Albers bounds that map units are measured from: x0, y0 is the origin and x1 − x0 the
 *  1,000 units of width. Two meshes decoded with the same frame line up exactly. */
export interface Frame {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface MapGeometry {
  /** IBGE code of each municipality, in the order of the topology. */
  ids: number[];
  /** Rings of each municipality, as flat [x0, y0, x1, y1, …] arrays in map units. */
  rings: Float32Array[][];
  /** Arcs between two shapes of different groups (only when a group is given). */
  borders: Float32Array[];
  /** Arcs of a single shape: the outer limit of the map. */
  outline: Float32Array[];
  /** Representative point of each municipality, [x0, y0, x1, y1, …]: always inside it
   *  (unlike the centroid of a crescent), where its circle and its tooltip go. */
  points: Float64Array;
  width: number;
  height: number;
  frame: Frame;
}

export interface DecodeOptions {
  /** Group of a shape: arcs between shapes of two groups are borders (the national map
   *  groups municipalities by state; the map of the states puts each in its own). */
  borderGroup?: (id: number) => number;
  /** Measure map units from these bounds instead of the mesh's own. */
  frame?: Frame;
  /** Called now and then so a long decode can give the main thread back. */
  pause?: () => Promise<void>;
}

type Shape = GeoTopoJson["objects"][string]["geometries"][number];

/** The polygons of a shape, each a list of rings of arc indexes. */
const polygonsOf = (shape: Shape): number[][][] =>
  shape.type === "Polygon" ? [shape.arcs as number[][]] : (shape.arcs as number[][][]);

/** State of a municipality, from its IBGE code (the first two digits). */
export const stateOf = (id: number) => Math.floor(id / 100000);

export async function decodeTopology(
  topo: GeoTopoJson,
  objectName: string,
  { borderGroup, frame: given, pause }: DecodeOptions,
): Promise<MapGeometry> {
  const object = topo.objects[objectName];
  if (!object) throw new Error(`no geometry collection "${objectName}" in the topology`);
  const shapes = object.geometries;
  // Gives the main thread back every ~12 ms of work, checked every 64 steps.
  let sliceStart = performance.now();
  let steps = 0;
  const tick = async () => {
    if (!pause || ++steps % 64 !== 0 || performance.now() - sliceStart < 12) return;
    await pause();
    sliceStart = performance.now();
  };
  // Quantized, as the data contract requires: integer positions, each a delta of the last.
  const [sx, sy] = topo.transform.scale;
  const [tx, ty] = topo.transform.translate;

  // 1. Every arc, delta-decoded and projected once; then shifted and scaled to map units.
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  const arcs: Float32Array[] = [];
  const projected: Float64Array[] = [];
  for (let a = 0; a < topo.arcs.length; a++) {
    const arc = topo.arcs[a] ?? [];
    const out = new Float64Array(arc.length * 2);
    let qx = 0;
    let qy = 0;
    for (let i = 0; i < arc.length; i++) {
      const point = arc[i] ?? [0, 0];
      qx += point[0];
      qy += point[1];
      const [x, y] = project(qx * sx + tx, qy * sy + ty);
      out[2 * i] = x;
      out[2 * i + 1] = y;
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
    projected.push(out);
    await tick();
  }
  const frame = given ?? { x0: minX, y0: minY, x1: maxX, y1: maxY };
  const scale = MAP_WIDTH / (frame.x1 - frame.x0);
  for (const p of projected) {
    const f = new Float32Array(p.length);
    for (let i = 0; i < p.length; i += 2) {
      f[i] = ((p[i] ?? 0) - frame.x0) * scale;
      f[i + 1] = ((p[i + 1] ?? 0) - frame.y0) * scale;
    }
    arcs.push(f);
    await tick();
  }

  // 2. Rings from their arcs (a negative index is the arc ~i walked backwards), and the
  //    municipalities on each side of every arc.
  const firstUser = new Int32Array(arcs.length).fill(-1);
  const users = new Uint8Array(arcs.length);
  const ids: number[] = [];
  const rings: Float32Array[][] = [];
  const ringOf = (indexes: number[], g: number) => {
    let length = 0;
    for (const index of indexes) length += (arcs[index < 0 ? ~index : index]?.length ?? 0) - 2;
    const ring = new Float32Array(length + 2);
    let at = 0;
    indexes.forEach((index, k) => {
      const a = index < 0 ? ~index : index;
      const arc = arcs[a] ?? new Float32Array();
      if (firstUser[a] !== g) {
        users[a] = (users[a] ?? 0) + 1;
        if (firstUser[a] === -1) firstUser[a] = g;
      }
      const n = arc.length / 2;
      for (let i = k === 0 ? 0 : 1; i < n; i++) {
        const j = index < 0 ? n - 1 - i : i;
        ring[at++] = arc[2 * j] ?? 0;
        ring[at++] = arc[2 * j + 1] ?? 0;
      }
    });
    return ring.subarray(0, at);
  };
  const points = new Float64Array(shapes.length * 2);
  for (let g = 0; g < shapes.length; g++) {
    const shape = shapes[g];
    if (!shape) continue;
    ids.push(shape.id);
    const polygons = polygonsOf(shape).map((polygon) => polygon.map((indexes) => ringOf(indexes, g)));
    rings.push(polygons.flat());
    const [x, y] = interiorPoint(polygons);
    points[2 * g] = x;
    points[2 * g + 1] = y;
    await tick();
  }

  // 3. The outer limit (arcs of one shape) and, if asked, the borders between groups.
  //    An arc has at most two shapes; the second is found by scanning its users.
  const second = new Int32Array(arcs.length).fill(-1);
  if (borderGroup) {
    shapes.forEach((shape, g) => {
      for (const polygon of polygonsOf(shape)) {
        for (const ring of polygon) {
          for (const index of ring) {
            const a = index < 0 ? ~index : index;
            if (firstUser[a] !== g) second[a] = g;
          }
        }
      }
    });
  }
  const borders: Float32Array[] = [];
  const outline: Float32Array[] = [];
  arcs.forEach((arc, a) => {
    if ((users[a] ?? 0) <= 1) outline.push(arc);
    else if (borderGroup) {
      const first = ids[firstUser[a] ?? -1];
      const other = ids[second[a] ?? -1];
      if (first !== undefined && other !== undefined && borderGroup(first) !== borderGroup(other)) {
        borders.push(arc);
      }
    }
  });

  return {
    ids,
    rings,
    borders,
    outline,
    points,
    width: MAP_WIDTH,
    height: (frame.y1 - frame.y0) * scale,
    frame,
  };
}

/** SVG path data of lines in map units: each point rounded (to `decimals` places), then
 *  written as a relative step from the previous rounded point, so the rounding never
 *  accumulates. */
export function linesToPath(lines: readonly Float32Array[], decimals = 1): string {
  const factor = 10 ** decimals;
  const r = (v: number) => Math.round(v * factor);
  const n = (units: number) => String(units / factor);
  const parts: string[] = [];
  for (const line of lines) {
    if (line.length < 4) continue;
    let px = r(line[0] ?? 0);
    let py = r(line[1] ?? 0);
    const steps: string[] = [];
    for (let i = 2; i < line.length; i += 2) {
      const x = r(line[i] ?? 0);
      const y = r(line[i + 1] ?? 0);
      if (x === px && y === py) continue;
      steps.push(`${n(x - px)} ${n(y - py)}`);
      px = x;
      py = y;
    }
    if (steps.length) parts.push(`M${n(r(line[0] ?? 0))} ${n(r(line[1] ?? 0))}l${steps.join(" ")}`);
  }
  // A minus sign separates two numbers by itself.
  return parts.join("").replace(/ -/g, "-");
}

/**
 * A point inside a (multi)polygon, as GEOS computes it for shapely's representative_point
 * (InteriorPointArea): for each polygon, a horizontal line at the middle of its box, moved
 * off any vertex; the crossings with its rings (holes included) split the line into
 * inside and outside stretches, and the point is the middle of the widest inside stretch
 * of all the polygons. Polygons are lists of rings, the outer ring first.
 */
export function interiorPoint(polygons: readonly (readonly Float32Array[])[]): [number, number] {
  let best: [number, number] | null = null;
  let bestWidth = -1;
  for (const polygon of polygons) {
    const outer = polygon[0];
    if (!outer || outer.length < 6) continue;
    let minY = Infinity;
    let maxY = -Infinity;
    for (let i = 1; i < outer.length; i += 2) {
      const y = outer[i] ?? 0;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
    // The scan line: halfway between the vertex heights closest to the centre, below and above.
    const centre = (minY + maxY) / 2;
    let below = minY;
    let above = maxY;
    for (const ring of polygon) {
      for (let i = 1; i < ring.length; i += 2) {
        const y = ring[i] ?? 0;
        if (y <= centre && y > below) below = y;
        if (y > centre && y < above) above = y;
      }
    }
    const scan = (below + above) / 2;
    const xs: number[] = [];
    for (const ring of polygon) {
      const n = ring.length / 2;
      for (let i = 0, j = n - 1; i < n; j = i++) {
        const xi = ring[2 * i] ?? 0;
        const yi = ring[2 * i + 1] ?? 0;
        const xj = ring[2 * j] ?? 0;
        const yj = ring[2 * j + 1] ?? 0;
        if (yi > scan !== yj > scan) xs.push(xi + ((scan - yi) * (xj - xi)) / (yj - yi));
      }
    }
    xs.sort((a, b) => a - b);
    for (let k = 0; k + 1 < xs.length; k += 2) {
      const width = (xs[k + 1] ?? 0) - (xs[k] ?? 0);
      if (width > bestWidth) {
        bestWidth = width;
        best = [((xs[k] ?? 0) + (xs[k + 1] ?? 0)) / 2, scan];
      }
    }
  }
  const first = polygons[0]?.[0];
  return best ?? [first?.[0] ?? 0, first?.[1] ?? 0];
}

/** Whether a point in map units falls inside a set of rings (even-odd rule). */
export function contains(rings: readonly Float32Array[], x: number, y: number): boolean {
  let inside = false;
  for (const ring of rings) {
    const n = ring.length / 2;
    for (let i = 0, j = n - 1; i < n; j = i++) {
      const xi = ring[2 * i] ?? 0;
      const yi = ring[2 * i + 1] ?? 0;
      const xj = ring[2 * j] ?? 0;
      const yj = ring[2 * j + 1] ?? 0;
      if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
    }
  }
  return inside;
}
