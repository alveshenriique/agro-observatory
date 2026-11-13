// Canvas 2D renderer of the Explorar map. The geometry (geometry.ts) is turned into one
// Path2D per municipality once, in map units, in slices so the main thread stays free; a
// size only sets the affine transform from map units to the screen. A frame fills the
// paths grouped by colour (one combined path per colour, so neighbours of the same class
// show no antialiasing seam), so changing the year or the measure only recolours. A hidden
// canvas paints every municipality in its own index colour for picking under the pointer,
// painted on the first pointer move and confirmed with a point-in-polygon test
// (antialiased borders can blend two colours into a third). A Delaunay triangulation of
// the representative points gives the neighbours for keyboard navigation. For the totals,
// proportional circles (lib/symbols.ts) go over a neutral base frame, largest first; the
// pointer picks the circle on top before the municipality under it.
import { Delaunay } from "d3-delaunay";

import { drawOrder } from "../../lib/symbols";
import { contains, MAP_PAD, type MapGeometry } from "./geometry";

/** Circles up to this radius (CSS px) have no outline and are filled together. */
export const TINY_PX = 1.5;

/** Fill codes of a frame: no data, zero published, a yield from too small a harvested
 *  area to compare (lib/classify.ts), then one code per class. */
export const CODE = { nodata: 0, zero: 1, small: 2, firstClass: 3 } as const;

export interface Palette {
  classes: string[];
  zero: string;
  hatch: string;
  background: string;
  borders: string;
  outline: string;
  /** Fill of the proportional circles (translucent, so overlaps stay readable). */
  circle: string;
}

interface Prepared {
  paths: Path2D[];
  borders: Path2D | null;
  outline: Path2D;
  delaunay: Delaunay<number>;
}

const prepared = new WeakMap<MapGeometry, Promise<Prepared>>();

/** Gives the main thread back between slices of work (scheduler.yield where it exists). */
export function pause(): Promise<void> {
  const scheduler = (globalThis as { scheduler?: { yield?: () => Promise<void> } }).scheduler;
  if (scheduler?.yield) return scheduler.yield();
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function pathOf(lines: readonly Float32Array[], close: boolean, into = new Path2D()): Path2D {
  for (const line of lines) {
    if (line.length < 4) continue;
    into.moveTo(line[0] ?? 0, line[1] ?? 0);
    for (let i = 2; i < line.length; i += 2) into.lineTo(line[i] ?? 0, line[i + 1] ?? 0);
    if (close) into.closePath();
  }
  return into;
}

async function prepare(geometry: MapGeometry): Promise<Prepared> {
  performance.mark("atlas:map-prepare:start");
  const paths: Path2D[] = [];
  let slice = performance.now();
  for (const rings of geometry.rings) {
    paths.push(pathOf(rings, true));
    if (performance.now() - slice > 12) {
      await pause();
      slice = performance.now();
    }
  }
  const borders = geometry.borders.length ? pathOf(geometry.borders, false) : null;
  const outline = pathOf(geometry.outline, false);
  await pause();
  const delaunay = new Delaunay(geometry.points);
  performance.measure("atlas:map-prepare", "atlas:map-prepare:start");
  return { paths, borders, outline, delaunay };
}

export class MapRenderer {
  private geometry: MapGeometry | null = null;
  private scene: Prepared | null = null;
  private thinBorders = false;
  private hit: HTMLCanvasElement | null = null;
  // The circles last drawn: radius per municipality in CSS px, and the drawing order.
  private circles: { radii: Float32Array; order: Int32Array } | null = null;
  private hitPainted = false;
  // Map units to CSS pixels: x' = k·x + ox, y' = k·y + oy.
  private k = 1;
  private ox = 0;
  private oy = 0;
  width = 0;
  height = 0;
  dpr = 1;

  private requested: MapGeometry | null = null;

  /** Loads a geometry (prepared once, then cached) and fits it to the current size.
   *  Resolves false if another geometry was asked for in the meantime. */
  async setGeometry(geometry: MapGeometry, thinBorders: boolean): Promise<boolean> {
    this.requested = geometry;
    if (!prepared.has(geometry)) prepared.set(geometry, prepare(geometry));
    const scene = await (prepared.get(geometry) as Promise<Prepared>);
    if (this.requested !== geometry) return false;
    this.geometry = geometry;
    this.scene = scene;
    this.thinBorders = thinBorders;
    this.fit();
    return true;
  }

  resize(width: number, height: number, dpr: number): void {
    this.width = width;
    this.height = height;
    this.dpr = dpr;
    this.fit();
  }

  private fit(): void {
    const g = this.geometry;
    if (!g || !this.width) return;
    // The same fit as the SVG outline's viewBox (MAP_PAD on every side, centred).
    this.k = Math.min(this.width / (g.width + 2 * MAP_PAD), this.height / (g.height + 2 * MAP_PAD));
    this.ox = (this.width - this.k * g.width) / 2;
    this.oy = (this.height - this.k * g.height) / 2;
    this.hitPainted = false;
    this.circles = null;
  }

  get count(): number {
    return this.scene?.paths.length ?? 0;
  }

  /** Draws one frame (a fill code per municipality) on a canvas sized for this scene. */
  draw(canvas: HTMLCanvasElement, codes: Uint8Array, palette: Palette): void {
    const ctx = canvas.getContext("2d");
    const scene = this.scene;
    if (!ctx || !scene) return;
    performance.mark("atlas:map-draw:start");
    const w = Math.round(this.width * this.dpr);
    const h = Math.round(this.height * this.dpr);
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const s = this.k * this.dpr;
    ctx.setTransform(s, 0, 0, s, this.ox * this.dpr, this.oy * this.dpr);
    const px = 1 / this.k; // one CSS pixel in map units, for line widths

    const groups: number[][] = Array.from({ length: CODE.firstClass + palette.classes.length }, () => []);
    codes.forEach((code, i) => groups[code]?.push(i));
    const fills: (string | CanvasPattern)[] = [
      hatchPattern(ctx, palette, s, this.dpr),
      palette.zero,
      dotPattern(ctx, palette, s, this.dpr),
      ...palette.classes,
    ];
    groups.forEach((members, code) => {
      const fill = fills[code];
      if (!fill || members.length === 0) return;
      const group = new Path2D();
      for (const i of members) {
        const p = scene.paths[i];
        if (p) group.addPath(p);
      }
      ctx.fillStyle = fill;
      ctx.fill(group);
    });
    ctx.lineJoin = "round";
    if (this.thinBorders) {
      const all = new Path2D();
      for (const p of scene.paths) all.addPath(p);
      ctx.strokeStyle = palette.background;
      ctx.lineWidth = 0.5 * px;
      ctx.stroke(all);
    }
    // State borders with a halo in the page colour, so they read over dark and light fills.
    if (scene.borders) {
      ctx.strokeStyle = palette.background;
      ctx.globalAlpha = 0.85;
      ctx.lineWidth = 1.6 * px;
      ctx.stroke(scene.borders);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = palette.borders;
      ctx.lineWidth = 0.6 * px;
      ctx.stroke(scene.borders);
    }
    ctx.strokeStyle = palette.outline;
    ctx.lineWidth = 0.9 * px;
    ctx.stroke(scene.outline);
    performance.measure("atlas:map-draw", "atlas:map-draw:start");
  }

  /**
   * Draws proportional circles over what the canvas already shows (the base frame), with
   * the context in CSS pixels at the given device pixel ratio. `radii` holds a radius per
   * municipality in CSS px, 0 for none; larger circles go first, smaller ones on top.
   */
  drawCircles(ctx: CanvasRenderingContext2D, radii: Float32Array, palette: Palette): number {
    const points = this.geometry?.points;
    if (!points) return 0;
    performance.mark("atlas:map-circles:start");
    const order = drawOrder(radii);
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.fillStyle = palette.circle;
    ctx.strokeStyle = palette.background;
    ctx.lineWidth = 0.75;
    // Circles of up to TINY_PX get no outline and come last in the order (smallest on top),
    // so they all go into one path and one fill: most circles are that small.
    const tiny = new Path2D();
    let tinyCount = 0;
    for (const i of order) {
      const r = radii[i] ?? 0;
      const x = this.k * (points[2 * i] ?? 0) + this.ox;
      const y = this.k * (points[2 * i + 1] ?? 0) + this.oy;
      if (r <= TINY_PX) {
        tiny.moveTo(x + r, y);
        tiny.arc(x, y, r, 0, 2 * Math.PI);
        tinyCount++;
        continue;
      }
      ctx.beginPath();
      ctx.arc(x, y, r, 0, 2 * Math.PI);
      ctx.fill();
      ctx.stroke();
    }
    if (tinyCount) ctx.fill(tiny);
    this.circles = { radii: Float32Array.from(radii), order };
    performance.measure("atlas:map-circles", "atlas:map-circles:start");
    return order.length;
  }

  /** Forgets the circles (a frame without them is on screen). */
  clearCircles(): void {
    this.circles = null;
  }

  /** Centre and radius of a municipality's circle as last drawn, in CSS px, if it has one. */
  circleOf(index: number): { x: number; y: number; r: number } | null {
    const r = this.circles?.radii[index] ?? 0;
    const p = this.point(index);
    return r > 0 && p ? { x: p[0], y: p[1], r } : null;
  }

  /** The circle on top under a point (the last drawn that contains it), or -1. */
  private pickCircle(x: number, y: number): number {
    const circles = this.circles;
    const points = this.geometry?.points;
    if (!circles || !points) return -1;
    for (let k = circles.order.length - 1; k >= 0; k--) {
      const i = circles.order[k] ?? -1;
      const r = Math.max(circles.radii[i] ?? 0, 3); // a few pixels of reach for the tiny ones
      const dx = x - (this.k * (points[2 * i] ?? 0) + this.ox);
      const dy = y - (this.k * (points[2 * i + 1] ?? 0) + this.oy);
      if (dx * dx + dy * dy <= r * r) return i;
    }
    return -1;
  }

  /** Index of the municipality under a point in CSS pixels, or -1: its circle if the point
   *  falls on one, else the municipality itself. */
  pick(x: number, y: number): number {
    const g = this.geometry;
    if (!g || x < 0 || y < 0 || x >= this.width || y >= this.height) return -1;
    const onCircle = this.pickCircle(x, y);
    if (onCircle >= 0) return onCircle;
    const ctx = this.paintHitCanvas();
    if (!ctx) return -1;
    const [r = 0, gr = 0, b = 0, a = 0] = ctx.getImageData(Math.floor(x), Math.floor(y), 1, 1).data;
    if (a < 255) return -1;
    const index = ((r << 16) | (gr << 8) | b) - 1;
    const rings = g.rings[index];
    if (!rings) return -1;
    return contains(rings, (x - this.ox) / this.k, (y - this.oy) / this.k) ? index : -1;
  }

  /** Representative point of a municipality, in CSS pixels. */
  point(index: number): [number, number] | undefined {
    const c = this.geometry?.points;
    if (!c || index < 0 || 2 * index >= c.length) return undefined;
    return [this.k * (c[2 * index] ?? 0) + this.ox, this.k * (c[2 * index + 1] ?? 0) + this.oy];
  }

  /** SVG path of one municipality in CSS pixels, for the highlight layer. */
  svgPath(index: number): string {
    const rings = this.geometry?.rings[index];
    if (!rings) return "";
    const n = (v: number) => Math.round(v * 10) / 10;
    return rings
      .map((ring) => {
        let d = "";
        for (let i = 0; i < ring.length; i += 2) {
          const x = n(this.k * (ring[i] ?? 0) + this.ox);
          const y = n(this.k * (ring[i + 1] ?? 0) + this.oy);
          d += `${i ? "L" : "M"}${x},${y}`;
        }
        return `${d}Z`;
      })
      .join("");
  }

  /** The neighbour that lies best in a direction (dx, dy), or the same index. */
  neighbour(index: number, dx: number, dy: number): number {
    const c = this.geometry?.points;
    const delaunay = this.scene?.delaunay;
    if (!c || !delaunay) return index;
    const fx = c[2 * index] ?? 0;
    const fy = c[2 * index + 1] ?? 0;
    let best = index;
    let bestScore = -Infinity;
    for (const j of delaunay.neighbors(index)) {
      const vx = (c[2 * j] ?? 0) - fx;
      const vy = (c[2 * j + 1] ?? 0) - fy;
      const length = Math.hypot(vx, vy) || 1;
      const cosine = (vx * dx + vy * dy) / length;
      const score = cosine - length / 1e5;
      if (cosine > 0.4 && score > bestScore) {
        bestScore = score;
        best = j;
      }
    }
    return best;
  }

  private paintHitCanvas(): CanvasRenderingContext2D | null {
    this.hit ??= document.createElement("canvas");
    const ctx = this.hit.getContext("2d", { willReadFrequently: true });
    const scene = this.scene;
    if (!ctx || !scene) return null;
    if (this.hitPainted) return ctx;
    performance.mark("atlas:map-hit:start");
    this.hit.width = Math.max(1, Math.round(this.width));
    this.hit.height = Math.max(1, Math.round(this.height));
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, this.hit.width, this.hit.height);
    ctx.setTransform(this.k, 0, 0, this.k, this.ox, this.oy);
    scene.paths.forEach((p, i) => {
      const id = i + 1;
      ctx.fillStyle = `rgb(${(id >> 16) & 255}, ${(id >> 8) & 255}, ${id & 255})`;
      ctx.fill(p);
    });
    this.hitPainted = true;
    performance.measure("atlas:map-hit", "atlas:map-hit:start");
    return ctx;
  }
}

const patterns = new WeakMap<CanvasRenderingContext2D, { key: string; pattern: CanvasPattern }>();

/** Diagonal hatching for "sem dado": a texture, so it never reads as a light value. The
 *  tile is drawn at the device resolution and scaled back from the map transform, so it
 *  keeps 6 CSS px at any map size. */
function hatchPattern(
  ctx: CanvasRenderingContext2D,
  palette: Palette,
  scale: number,
  dpr: number,
): CanvasPattern | string {
  const density = Math.max(1, Math.round(dpr));
  const key = `${palette.hatch}/${palette.background}/${density}`;
  const cached = patterns.get(ctx);
  let pattern = cached?.key === key ? cached.pattern : undefined;
  if (!pattern) {
    const size = 6 * density;
    const tile = document.createElement("canvas");
    tile.width = size;
    tile.height = size;
    const t = tile.getContext("2d");
    if (!t) return palette.background;
    t.fillStyle = palette.background;
    t.fillRect(0, 0, size, size);
    t.strokeStyle = palette.hatch;
    t.lineWidth = density;
    t.beginPath();
    t.moveTo(-density, size + density);
    t.lineTo(size + density, -density);
    t.stroke();
    const created = ctx.createPattern(tile, "repeat");
    if (!created) return palette.background;
    pattern = created;
    patterns.set(ctx, { key, pattern });
  }
  // A tile pixel spans dpr/density device pixels; the fill runs under the map scale.
  pattern.setTransform(new DOMMatrix().scale(dpr / density / scale));
  return pattern;
}

const dots = new WeakMap<CanvasRenderingContext2D, { key: string; pattern: CanvasPattern }>();

/** Dots for a yield from too small a harvested area: a texture of its own, neither the
 *  hatching of "sem dado" nor a tone of the ramp. Same scaling as the hatching. */
function dotPattern(
  ctx: CanvasRenderingContext2D,
  palette: Palette,
  scale: number,
  dpr: number,
): CanvasPattern | string {
  const density = Math.max(1, Math.round(dpr));
  const key = `${palette.hatch}/${palette.zero}/${density}`;
  const cached = dots.get(ctx);
  let pattern = cached?.key === key ? cached.pattern : undefined;
  if (!pattern) {
    const size = 5 * density;
    const tile = document.createElement("canvas");
    tile.width = size;
    tile.height = size;
    const t = tile.getContext("2d");
    if (!t) return palette.zero;
    t.fillStyle = palette.zero;
    t.fillRect(0, 0, size, size);
    t.fillStyle = palette.hatch;
    t.beginPath();
    t.arc(size / 2, size / 2, 0.85 * density, 0, 2 * Math.PI);
    t.fill();
    const created = ctx.createPattern(tile, "repeat");
    if (!created) return palette.zero;
    pattern = created;
    dots.set(ctx, { key, pattern });
  }
  pattern.setTransform(new DOMMatrix().scale(dpr / density / scale));
  return pattern;
}
