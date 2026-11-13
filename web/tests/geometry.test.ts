import { geoConicEqualArea } from "d3-geo";

import {
  contains,
  decodeTopology,
  interiorPoint,
  linesToPath,
  MAP_WIDTH,
  project,
  stateOf,
} from "../src/components/explore/geometry";
import type { GeoTopoJson } from "../src/types/data/topology";

describe("the Explorar projection", () => {
  it("is d3's conic equal-area with the parameters of SIRGAS 2000 / Brazil Albers", () => {
    const d3 = geoConicEqualArea()
      .parallels([-2, -22])
      .rotate([54, 0])
      .scale(1)
      .translate([0, 0])
      .precision(0);
    const places: [number, number][] = [
      [-55.7, -12.5], // Sorriso
      [-73.9, -7.5], // far west
      [-34.8, -7.1], // far east
      [-53.4, -33.7], // far south
      [-60.2, 5.2], // far north
    ];
    const [ox, oy] = project(...places[0]!);
    const [dx, dy] = d3(places[0]!)!;
    for (const place of places) {
      const [x, y] = project(...place);
      const [ex, ey] = d3(place)!;
      expect(x - ox).toBeCloseTo(ex - dx, 12);
      expect(y - oy).toBeCloseTo(ey - dy, 12);
    }
  });
});

// Two unit squares side by side, in two states, sharing their middle edge (arc 0):
//   arc 0: (1,0) → (1,1), shared; arc 1: the rest of the left square; arc 2: the right one.
const topology = {
  type: "Topology",
  bbox: [0, 0, 2, 1],
  transform: { scale: [1, 1], translate: [-55, -15] },
  arcs: [
    [
      [1, 0],
      [0, 1],
    ],
    [
      [1, 1],
      [-1, 0],
      [0, -1],
      [1, 0],
    ],
    [
      [1, 0],
      [1, 0],
      [0, 1],
      [-1, 0],
    ],
  ],
  objects: {
    municipalities: {
      type: "GeometryCollection",
      geometries: [
        { type: "Polygon", id: 5100102, arcs: [[0, 1]] },
        { type: "MultiPolygon", id: 5200050, arcs: [[[2, -1]]] },
      ],
    },
  },
} as unknown as GeoTopoJson;

describe("decoding the TopoJSON of the data package", () => {
  it("builds each ring from its arcs, walking negative ones backwards", async () => {
    const geometry = await decodeTopology(topology, "municipalities", { borderGroup: stateOf });
    expect(geometry.ids).toEqual([5100102, 5200050]);
    expect(geometry.width).toBe(MAP_WIDTH);
    expect(geometry.rings.map((rings) => rings.length)).toEqual([1, 1]);
    // Each ring closes where it starts, with the shared arc's two points once.
    for (const [ring] of geometry.rings) {
      expect(ring).toBeDefined();
      expect(ring!.length).toBe(10);
      expect(ring![0]).toBeCloseTo(ring![8]!, 4);
      expect(ring![1]).toBeCloseTo(ring![9]!, 4);
    }
  });

  it("separates the outer limit from the borders between states", async () => {
    const both = await decodeTopology(topology, "municipalities", { borderGroup: stateOf });
    expect(both.borders).toHaveLength(1);
    expect(both.outline).toHaveLength(2);
    const sameState = structuredClone(topology);
    const shapes = sameState.objects.municipalities?.geometries ?? [];
    if (shapes[1]) shapes[1].id = 5100201;
    const one = await decodeTopology(sameState, "municipalities", { borderGroup: stateOf });
    expect(one.borders).toHaveLength(0);
    expect(one.outline).toHaveLength(2);
    const none = await decodeTopology(topology, "municipalities", {});
    expect(none.borders).toHaveLength(0);
  });

  it("puts the representative point inside and tells inside from outside", async () => {
    const geometry = await decodeTopology(topology, "municipalities", {});
    const [left, right] = geometry.rings;
    const c = geometry.points;
    expect(c[0]).toBeLessThan(c[2]!);
    expect(contains(left!, c[0]!, c[1]!)).toBe(true);
    expect(contains(right!, c[0]!, c[1]!)).toBe(false);
    expect(contains(right!, c[2]!, c[3]!)).toBe(true);
  });
});

describe("the outline drawn before the municipalities", () => {
  it("lines up with the municipalities when decoded in the same frame", async () => {
    const wide = structuredClone(topology);
    wide.transform.translate = [-56, -15];
    const own = await decodeTopology(topology, "municipalities", {});
    const shared = await decodeTopology(wide, "municipalities", { frame: own.frame });
    // The same frame: a point shifted one degree west sits further left by the same amount.
    expect(shared.frame).toEqual(own.frame);
    expect(shared.rings[0]![0]![0]).toBeLessThan(own.rings[0]![0]![0]!);
    expect(shared.width).toBe(own.width);
  });

  it("writes SVG steps from rounded points, so the rounding never adds up", () => {
    const line = new Float32Array([0, 0, 0.04, 0, 0.08, 0, 0.12, 0, 10.26, -3.31]);
    const d = linesToPath([line]);
    expect(d).toBe("M0 0l0.1 0 10.2-3.3");
    // Summing the steps lands on the rounded last point.
    const [, steps = ""] = d.split("l");
    const numbers = steps.replace(/-/g, " -").trim().split(/\s+/).map(Number);
    const x = numbers.filter((_, i) => i % 2 === 0).reduce((a, b) => a + b, 0);
    expect(x).toBeCloseTo(10.3, 6);
  });
});

describe("the representative point", () => {
  // A U whose centroid falls in the gap between its arms, outside the shape.
  const u = new Float32Array([0, 0, 3, 0, 3, 3, 2, 3, 2, 1, 1, 1, 1, 3, 0, 3, 0, 0]);

  it("stays inside a crescent-like shape, where the centroid would not", () => {
    const [x, y] = interiorPoint([[u]]);
    expect(contains([u], x, y)).toBe(true);
    expect(contains([u], 1.5, 1.8)).toBe(false); // about where the centroid is
  });

  it("avoids a hole and picks the widest part of a multipolygon", () => {
    const square = new Float32Array([0, 0, 4, 0, 4, 4, 0, 4, 0, 0]);
    const hole = new Float32Array([1, 1, 1, 3, 3, 3, 3, 1, 1, 1]);
    const islet = new Float32Array([10, 0, 10.5, 0, 10.5, 0.5, 10, 0.5, 10, 0]);
    const [x, y] = interiorPoint([[islet], [square, hole]]);
    expect(contains([square, hole], x, y)).toBe(true);
    expect(x).toBeLessThan(4);
  });
});
