// The Explorar island: the title sentence with its filters, the map (canvas 2D, highlight
// layer, accessible tooltip), the legend, the timeline and the table view. Totals
// (production, areas, value) are proportional circles over a neutral base map; the yield,
// a ratio, is a choropleth with fixed classes. The view lives in the URL. Every number
// cites its file in the data package (lib/provenance.ts), including the legend's circle
// references and class limits, which the provenance test recomputes.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { CLASS_COUNT, cellState, isSmallArea, yieldCell } from "../../lib/classify";
import { CIRCLE_MAX_RADIUS, CIRCLE_MIN_RADIUS_PX, circleRadius } from "../../lib/symbols";
import { clampYear, type ExploreView as View, type Measure, parseView, serializeView } from "../../lib/explore-view";
import { format } from "../../lib/format";
import { usePrefersReducedMotion } from "../../lib/usePrefersReducedMotion";
import {
  type ExploreFile,
  fetchJson,
  type Geo,
  loadNational,
  loadState,
  type Municipalities,
  rowsOf,
} from "./data";
import { type Frame, MAP_PAD, MAP_WIDTH } from "./geometry";
import { CODE, MapRenderer, type Palette, TINY_PX } from "./map-renderer";

export interface SeriesOption {
  id: string;
  phrase: string;
  /** Article of the crop in a sentence ("a soja", "o milho"). */
  article: string;
  firstYear: number;
  lastYear: number;
  valueFirstYear: number;
  areaPhrase: string;
  areaLabel: string;
  productionUnit: string;
}

/** The fixed scale of a series and measure: circles for totals, classes for the yield. */
export type Scale = { kind: "circles"; max: number; refs: number[] } | { kind: "classes"; breaks: number[] };

export interface Props {
  dataBase: string;
  series: SeriesOption[];
  ufs: { abbr: string; name: string }[];
  scales: Record<string, Record<string, Scale>>;
  defaults: View;
  aspect: number;
  baseYear: { text: string; src: string };
  /** Albers frame of the national mesh, shared with the outline drawn at build time. */
  frame: Frame;
  /** The outline of the states (an SVG made at build time), shown until the first frame. */
  children?: React.ReactNode;
}

const STEP_MS = 900;
// A step of the timeline: the base frames cross-fade and the circles grow or shrink.
const TRANSITION_MS = 450;
const ease = (t: number) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);

const MEASURE_PHRASE: Record<Measure, (s: SeriesOption) => string> = {
  production_t: () => "em toneladas",
  harvested_area_ha: () => "em hectares colhidos",
  planted_or_bearing_area_ha: (s) => (s.areaPhrase === "área em produção" ? "em hectares em produção" : "em hectares plantados"),
  production_value_real_thousand_brl: () => "em valor da produção",
  yield: () => "em quilos por hectare",
};

const MEASURE_LABEL: Record<Measure, (s: SeriesOption) => string> = {
  production_t: () => "Produção",
  harvested_area_ha: () => "Área colhida",
  planted_or_bearing_area_ha: (s) => s.areaLabel,
  production_value_real_thousand_brl: () => "Valor da produção",
  yield: () => "Rendimento",
};

const fileOf = (series: string, measure: string) => `explore/${series}/${measure}.json`;

function readPalette(): Palette {
  const style = getComputedStyle(document.documentElement);
  const v = (name: string) => style.getPropertyValue(name).trim();
  return {
    classes: [2, 3, 4, 5, 6].map((k) => v(`--color-seq-${k}`)),
    zero: v("--color-seq-1"),
    hatch: v("--color-text-muted"),
    background: v("--color-background"),
    borders: v("--color-text-muted"),
    outline: v("--color-text-secondary"),
    circle: translucent(v("--color-seq-5"), 0.82),
  };
}

/** A #rrggbb colour with an alpha, as rgba(). */
function translucent(hex: string, alpha: number): string {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  if (!m) return hex;
  return `rgba(${parseInt(m[1] ?? "0", 16)}, ${parseInt(m[2] ?? "0", 16)}, ${parseInt(m[3] ?? "0", 16)}, ${alpha})`;
}

interface Reading {
  /** "small": a yield from a harvested area too small to compare (not classed). */
  kind: "nodata" | "zero" | "value" | "small" | "unavailable";
  value?: number;
  src?: string;
}

/** Sizes a select to its chosen option where CSS field-sizing is not supported. */
function useFitSelect(ref: React.RefObject<HTMLSelectElement | null>, text: string) {
  useEffect(() => {
    const select = ref.current;
    if (!select || CSS.supports("field-sizing", "content")) return;
    const context = document.createElement("canvas").getContext("2d");
    if (!context) return;
    const fit = () => {
      const style = getComputedStyle(select);
      context.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      select.style.width = `${Math.ceil(context.measureText(text).width) + 2}px`;
    };
    fit();
    void document.fonts.ready.then(fit);
  }, [ref, text]);
}

export default function ExploreView(props: Props) {
  const { dataBase, series, ufs, scales, defaults } = props;
  const [view, setView] = useState<View>(defaults);
  // The island renders the default view on the server; the URL is read once on mount, and
  // nothing is fetched or written back before that, so a permanent link loads only its data.
  const [urlRead, setUrlRead] = useState(false);
  const [national, setNational] = useState<Geo | null>(null);
  const [states, setStates] = useState<Record<string, Geo>>({});
  const [files, setFiles] = useState<Record<string, ExploreFile>>({});
  const [names, setNames] = useState<Municipalities["municipalities"] | null>(null);
  const [playing, setPlaying] = useState(false);
  const [tableOpen, setTableOpen] = useState(false);
  const [hover, setHover] = useState<{ index: number; x: number; y: number } | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [size, setSize] = useState<{ width: number; height: number } | null>(null);
  const [failed, setFailed] = useState(false);
  const [sort, setSort] = useState<{ key: "name" | "value"; descending: boolean }>({ key: "value", descending: true });
  const [href, setHref] = useState("");
  const reduceMotion = usePrefersReducedMotion();
  const seriesSelect = useRef<HTMLSelectElement>(null);
  const measureSelect = useRef<HTMLSelectElement>(null);
  const yearSelect = useRef<HTMLSelectElement>(null);

  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<MapRenderer | null>(null);
  const blendRef = useRef<number>(0);
  const paletteRef = useRef<Palette | null>(null);
  const [paletteVersion, setPaletteVersion] = useState(0);

  const option = series.find((s) => s.id === view.series) ?? series[0];
  if (!option) throw new Error("no series to explore");
  const years = useMemo(
    () => Array.from({ length: option.lastYear - option.firstYear + 1 }, (_, i) => option.firstYear + i),
    [option],
  );
  const yearIndex = view.year - option.firstYear;
  const yearSrc = (year: number) => `${fileOf(option.id, "production_t")}#/years/${year - option.firstYear}|year`;
  const isYield = view.measure === "yield";
  const measureFiles = isYield
    ? [fileOf(option.id, "production_t"), fileOf(option.id, "harvested_area_ha")]
    : [fileOf(option.id, view.measure)];
  const unit = isYield
    ? "kg/ha"
    : view.measure === "production_t"
      ? option.productionUnit
      : view.measure === "production_value_real_thousand_brl"
        ? "mil R$"
        : "ha";
  const valueUnavailable =
    view.measure === "production_value_real_thousand_brl" && view.year < option.valueFirstYear;
  const scale = scales[option.id]?.[view.measure];
  const mode = scale?.kind ?? (isYield ? "classes" : "circles");
  const currentBreaks = scale?.kind === "classes" ? scale.breaks : [];
  const circleMax = scale?.kind === "circles" ? scale.max : 0;
  const breakSrc = (k: number) => `${fileOf(option.id, "production_t")}#/values!ybreak:${k}|int`;
  const circleSrc = (k: number) => `${fileOf(option.id, view.measure)}#/values!circle:${k}|int`;

  // --- The view in the URL. ---
  useEffect(() => {
    const ranges = series.map((s) => ({ id: s.id, firstYear: s.firstYear, lastYear: s.lastYear }));
    setView(parseView(window.location.search, ranges, ufs.map((u) => u.abbr), defaults));
    setUrlRead(true);
  }, [series, ufs, defaults]);

  useEffect(() => {
    if (!urlRead) return;
    const search = serializeView(view);
    if (window.location.search !== search) window.history.replaceState(null, "", search);
    setHref(`${window.location.pathname}${search}`);
  }, [view, urlRead]);

  // --- Data. ---
  const loadNames = useCallback(() => {
    if (names) return;
    fetchJson<Municipalities>(dataBase, "municipalities.json")
      .then((data) => setNames(data.municipalities))
      .catch(() => setFailed(true));
  }, [dataBase, names]);

  useEffect(() => {
    if (!urlRead || view.uf !== null || national) return;
    loadNational(dataBase, props.frame)
      .then(setNational)
      .catch(() => setFailed(true));
  }, [dataBase, view.uf, national, urlRead]);

  useEffect(() => {
    const uf = view.uf;
    if (!urlRead || uf === null || states[uf]) return;
    loadNames();
    loadState(dataBase, uf)
      .then((geo) => setStates((loaded) => ({ ...loaded, [uf]: geo })))
      .catch(() => setFailed(true));
  }, [dataBase, view.uf, states, loadNames, urlRead]);

  useEffect(() => {
    if (!urlRead) return;
    for (const file of measureFiles) {
      if (files[file]) continue;
      fetchJson<ExploreFile>(dataBase, file)
        .then((data) => setFiles((loaded) => ({ ...loaded, [file]: data })))
        .catch(() => setFailed(true));
    }
  }, [dataBase, measureFiles.join(","), files, urlRead]);

  useEffect(() => {
    if (tableOpen) loadNames();
  }, [tableOpen, loadNames]);

  // --- Geometry in focus, and the matrix row of each of its municipalities. ---
  const geo = view.uf === null ? national : (states[view.uf] ?? null);
  const rows = useMemo(() => {
    if (!geo) return null;
    if (view.uf === null) return geo.ids.map((_, i) => i);
    return names ? rowsOf(geo.ids, names.municipality_id) : null;
  }, [geo, view.uf, names]);

  // --- What each municipality reads in this view (any year, for the frame drawn ahead). ---
  const readingAt = useCallback(
    (row: number, year: number): Reading => {
      if (view.measure === "production_value_real_thousand_brl" && year < option.valueFirstYear) {
        return { kind: "unavailable" };
      }
      if (isYield) {
        const production = files[fileOf(option.id, "production_t")];
        const area = files[fileOf(option.id, "harvested_area_ha")];
        if (!production || !area) return { kind: "nodata" };
        const col = year - (production.years[0] ?? 0);
        const harvested = area.values[row]?.[col] ?? null;
        const value = yieldCell(production.values[row]?.[col] ?? null, harvested);
        if (value === null) return { kind: "nodata" };
        if (value === 0) return { kind: "zero" };
        const src = `${fileOf(option.id, "production_t")}#/values/${row}/${col}!yield|int`;
        return { kind: isSmallArea(harvested) ? "small" : "value", value, src };
      }
      const file = files[fileOf(option.id, view.measure)];
      if (!file) return { kind: "nodata" };
      const col = year - (file.years[0] ?? 0);
      const value = col >= 0 ? (file.values[row]?.[col] ?? null) : null;
      if (value === null) return { kind: "nodata" };
      if (value === 0) return { kind: "zero" };
      return { kind: "value", value, src: `${fileOf(option.id, view.measure)}#/values/${row}/${col}|int` };
    },
    [files, isYield, option.id, option.valueFirstYear, view.measure],
  );
  const reading = useCallback((row: number) => readingAt(row, view.year), [readingAt, view.year]);

  const ready = geo !== null && rows !== null && measureFiles.every((f) => files[f]);
  // The base frame of a year: in the choropleth, the class of each municipality; under the
  // circles, a light tone for every municipality with data. No data is hatched in both.
  const codesFor = useCallback(
    (year: number) => {
      if (!ready || !rows) return null;
      const out = new Uint8Array(rows.length);
      rows.forEach((row, i) => {
        const r = readingAt(row, year);
        if (r.kind === "nodata" || r.kind === "unavailable") out[i] = CODE.nodata;
        else if (r.kind === "small") out[i] = CODE.small;
        else if (mode === "circles" || r.kind === "zero" || r.value === undefined) out[i] = CODE.zero;
        else {
          const state = cellState(r.value, currentBreaks);
          out[i] = state.kind === "value" ? CODE.firstClass + state.cls : CODE.nodata;
        }
      });
      return out;
    },
    [ready, rows, readingAt, currentBreaks, mode],
  );
  const codes = useMemo(() => codesFor(view.year), [codesFor, view.year]);

  // CSS pixels per map unit of the national map in this box: circles keep the national
  // scale when a state is in focus, and the legend (sized in container units) matches it.
  const pxPerUnit = size ? size.width / (MAP_WIDTH + 2 * MAP_PAD) : 0;
  const radiiFor = useCallback(
    (year: number) => {
      if (mode !== "circles" || !ready || !rows || !circleMax || !pxPerUnit) return null;
      const out = new Float32Array(rows.length);
      const maxRadius = CIRCLE_MAX_RADIUS * pxPerUnit;
      rows.forEach((row, i) => {
        const r = readingAt(row, year);
        out[i] = r.kind === "value" && r.value ? circleRadius(r.value, circleMax, maxRadius, CIRCLE_MIN_RADIUS_PX) : 0;
      });
      return out;
    },
    [mode, ready, rows, circleMax, pxPerUnit, readingAt],
  );

  const counts = useMemo(() => {
    if (!ready || !rows) return null;
    const out = { nodata: 0, zero: 0, value: 0, small: 0 };
    for (const row of rows) {
      const kind = reading(row).kind;
      if (kind === "value") out.value++;
      else if (kind === "small") out.small++;
      else if (kind === "zero") out.zero++;
      else out.nodata++;
    }
    return out;
  }, [ready, rows, reading]);

  // --- Size, palette and scene. ---
  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const observer = new ResizeObserver(([entry]) => {
      const width = Math.round(entry?.contentRect.width ?? 0);
      if (width > 0) setSize((old) => (old?.width === width ? old : { width, height: Math.round(width * props.aspect) }));
    });
    observer.observe(wrap);
    return () => observer.disconnect();
  }, [props.aspect]);

  useEffect(() => {
    paletteRef.current = readPalette();
    const scheme = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => {
      paletteRef.current = readPalette();
      setPaletteVersion((v) => v + 1);
    };
    scheme.addEventListener("change", update);
    return () => scheme.removeEventListener("change", update);
  }, []);

  // The geometry the renderer holds (prepared in slices, so it can lag behind the focus),
  // and a counter bumped at every new geometry or size.
  const [sceneGeo, setSceneGeo] = useState<Geo | null>(null);
  const [sceneVersion, setSceneVersion] = useState(0);
  useEffect(() => {
    if (!geo) return;
    let current = true;
    const renderer = (rendererRef.current ??= new MapRenderer());
    void renderer.setGeometry(geo.geometry, geo.thinBorders).then((held) => {
      if (!current || !held) return;
      setSceneGeo(geo);
      setHover(null);
      setSelected(null);
      setSceneVersion((v) => v + 1);
    });
    return () => {
      current = false;
    };
  }, [geo]);
  useEffect(() => {
    if (!size) return;
    const renderer = (rendererRef.current ??= new MapRenderer());
    renderer.resize(size.width, size.height, Math.min(window.devicePixelRatio || 1, 2));
    setHover(null);
    setSceneVersion((v) => v + 1);
  }, [size]);

  // --- Drawing. A base frame (the choropleth, or the neutral map under the circles) is drawn
  // on one of three offscreen canvases and shown on the visible one, with the circles drawn
  // over it. While the timeline plays, the next year's base is drawn and rasterised ahead,
  // in the pause between two steps (rasterising the fills is the costly part of a frame),
  // and a year with the same base as the last reuses its canvas. A step then cross-fades
  // the bases and moves the circles from their old radius to the new one; with reduced
  // motion it jumps.
  const viewKey = `${view.series}/${view.measure}/${view.year}/${view.uf ?? "BR"}`;
  const sceneKey = `${view.series}/${view.measure}/${view.uf ?? "BR"}/${paletteVersion}/${sceneVersion}`;
  const [shown, setShown] = useState<string | null>(null);
  // Loading: the map group is busy until the frame of the view is on screen. The line that
  // says so appears only if that takes a moment (never during play, whose frames are ready),
  // so the live region does not announce every step; it starts visible, as on the server.
  const loading = !failed && shown !== viewKey;
  const geometryPending = !geo || sceneGeo !== geo;
  const [slowLoading, setSlowLoading] = useState(true);
  useEffect(() => {
    if (!loading) {
      setSlowLoading(false);
      return;
    }
    const timer = window.setTimeout(() => setSlowLoading(true), 300);
    return () => window.clearTimeout(timer);
  }, [loading]);
  // The outline from the build stands in for the national map until its first frame.
  const outlineVisible = shown === null && (!urlRead || view.uf === null);
  const playingRef = useRef(playing);
  playingRef.current = playing;
  const reduceMotionRef = useRef(reduceMotion);
  reduceMotionRef.current = reduceMotion;

  interface Shown {
    canvas: HTMLCanvasElement;
    codes: Uint8Array;
    radii: Float32Array | null;
    scene: string;
    year: number;
  }
  const poolRef = useRef<HTMLCanvasElement[] | null>(null);
  const layerRef = useRef<HTMLCanvasElement | null>(null);
  const shownFrame = useRef<Shown | null>(null);
  const aheadFrame = useRef<Shown | null>(null);
  const aheadTimer = useRef(0);
  const [, setCirclesVersion] = useState(0);

  /** A frame for a year: the base canvas (reused when the base did not change) and radii. */
  const frameFor = useCallback(
    (year: number, busy: (HTMLCanvasElement | undefined)[]): Shown | null => {
      const renderer = rendererRef.current;
      const palette = paletteRef.current;
      const pool = (poolRef.current ??= [0, 1, 2].map(() => document.createElement("canvas")));
      const yearCodes = codesFor(year);
      if (!renderer || !palette || !yearCodes) return null;
      const radii = radiiFor(year);
      const last = shownFrame.current;
      const same =
        last && last.scene === sceneKey && last.codes.length === yearCodes.length && last.codes.every((c, i) => c === yearCodes[i]);
      if (same) return { canvas: last.canvas, codes: yearCodes, radii, scene: sceneKey, year };
      const canvas = pool.find((c) => !busy.includes(c)) ?? pool[0]!;
      renderer.draw(canvas, yearCodes, palette);
      return { canvas, codes: yearCodes, radii, scene: sceneKey, year };
    },
    [codesFor, radiiFor, sceneKey],
  );

  useEffect(() => {
    const renderer = rendererRef.current;
    const canvas = canvasRef.current;
    const palette = paletteRef.current;
    if (!renderer || !canvas || !codes || !palette || !size || sceneGeo !== geo) return;
    const previous = shownFrame.current;
    if (previous?.scene === sceneKey && previous.year === view.year) return;
    const ahead = aheadFrame.current;
    const target =
      ahead?.scene === sceneKey && ahead.year === view.year
        ? { ...ahead, radii: radiiFor(view.year) }
        : frameFor(view.year, [previous?.canvas, ahead?.canvas]);
    if (!target) return;
    aheadFrame.current = null;
    window.clearTimeout(aheadTimer.current);
    // Animate only between consecutive years of the same view while playing.
    const animate = playingRef.current && !reduceMotionRef.current && previous?.scene === sceneKey;
    shownFrame.current = target;
    if (wrapRef.current) wrapRef.current.dataset.transition = animate ? "blend" : "jump";
    setShown(viewKey);
    cancelAnimationFrame(blendRef.current);
    if (canvas.width !== target.canvas.width || canvas.height !== target.canvas.height) {
      canvas.width = target.canvas.width;
      canvas.height = target.canvas.height;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // The next year, drawn ahead once this one is on screen.
    const drawAhead = () => {
      if (!playingRef.current || view.year >= option.lastYear) return;
      aheadTimer.current = window.setTimeout(() => {
        if (!playingRef.current) return;
        performance.mark("atlas:map-ahead:start");
        const next = frameFor(view.year + 1, [shownFrame.current?.canvas]);
        if (!next) return;
        aheadFrame.current = next;
        void createImageBitmap(next.canvas).then((bitmap) => {
          bitmap.close();
          performance.measure("atlas:map-ahead", "atlas:map-ahead:start");
        });
      }, 50);
    };

    // One picture: the bases (the old one fading out), then the circles. During a step only
    // the circles larger than TINY_PX at either end grow or shrink frame by frame; the tiny
    // ones (most of them: no outline, always on top) go once, at their new size, into a layer
    // laid over the moving ones, so a frame rasterises a few hundred circles, not thousands.
    // The last frame draws them all.
    const from = animate ? previous : null;
    const between = target.radii ? new Float32Array(target.radii.length) : null;
    let moving: Uint8Array | null = null;
    let tinyLayer: HTMLCanvasElement | null = null;
    if (from && target.radii) {
      const n = target.radii.length;
      moving = new Uint8Array(n);
      const tiny = new Float32Array(n);
      for (let i = 0; i < n; i++) {
        const r1 = target.radii[i] ?? 0;
        if (Math.max(from.radii?.[i] ?? 0, r1) > TINY_PX) moving[i] = 1;
        else tiny[i] = r1;
      }
      tinyLayer = layerRef.current ??= document.createElement("canvas");
      tinyLayer.width = canvas.width;
      tinyLayer.height = canvas.height;
      const layer = tinyLayer.getContext("2d");
      if (layer) renderer.drawCircles(layer, tiny, palette);
    }
    const paint = (t: number) => {
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.globalAlpha = 1;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (from && from.canvas !== target.canvas && t < 1) {
        ctx.drawImage(from.canvas, 0, 0);
        ctx.globalAlpha = t;
      }
      ctx.drawImage(target.canvas, 0, 0);
      ctx.globalAlpha = 1;
      if (target.radii && between) {
        const old = from?.radii;
        const partial = t < 1 && moving !== null && tinyLayer !== null;
        for (let i = 0; i < between.length; i++) {
          const r1 = target.radii[i] ?? 0;
          if (!partial) between[i] = r1;
          else between[i] = moving?.[i] ? (old?.[i] ?? 0) + (r1 - (old?.[i] ?? 0)) * t : 0;
        }
        const drawn = renderer.drawCircles(ctx, between, palette);
        if (partial && tinyLayer) {
          ctx.setTransform(1, 0, 0, 1, 0, 0);
          ctx.drawImage(tinyLayer, 0, 0);
        }
        if (wrapRef.current && !partial) wrapRef.current.dataset.circles = String(drawn);
      } else {
        renderer.clearCircles();
        if (wrapRef.current) wrapRef.current.dataset.circles = "0";
      }
    };

    if (!from) {
      paint(1);
      setCirclesVersion((v) => v + 1);
      drawAhead();
      return;
    }
    const start = performance.now();
    performance.mark("atlas:map-blend:start");
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / TRANSITION_MS);
      paint(ease(t));
      if (t < 1) blendRef.current = requestAnimationFrame(step);
      else {
        performance.measure("atlas:map-blend", "atlas:map-blend:start");
        setCirclesVersion((v) => v + 1);
        drawAhead();
      }
    };
    blendRef.current = requestAnimationFrame(step);
  }, [codes, frameFor, radiiFor, sceneGeo, geo, size, viewKey, sceneKey, view.year, option.lastYear]);

  // Starting to play draws the next year ahead right away.
  useEffect(() => {
    if (!playing || aheadFrame.current || view.year >= option.lastYear) return;
    const next = frameFor(view.year + 1, [shownFrame.current?.canvas]);
    if (!next) return;
    aheadFrame.current = next;
    void createImageBitmap(next.canvas).then((bitmap) => bitmap.close());
  }, [playing]);

  // --- Timeline: play steps one year at a time; never starts by itself. ---
  useEffect(() => {
    if (!playing) return;
    const timer = window.setTimeout(() => {
      setView((v) => {
        if (v.year >= option.lastYear) {
          setPlaying(false);
          return v;
        }
        return { ...v, year: v.year + 1 };
      });
    }, STEP_MS);
    return () => window.clearTimeout(timer);
  }, [playing, view.year, option.lastYear]);

  const togglePlay = () => {
    if (!playing && view.year >= option.lastYear) setView((v) => ({ ...v, year: option.firstYear }));
    setPlaying((p) => !p);
  };

  // --- Pointer and keyboard. ---
  const active = hover?.index ?? selected;
  const activeRow = active !== null && rows ? (rows[active] ?? -1) : -1;
  const activeId = active !== null && geo ? geo.ids[active] : undefined;
  const openFicha = (index: number) => {
    const id = geo?.ids[index];
    if (id) window.location.assign(`/municipio/${id}/`);
  };
  const pointAt = (event: React.PointerEvent | React.MouseEvent) => {
    const box = canvasRef.current?.getBoundingClientRect();
    if (!box) return null;
    return { x: event.clientX - box.left, y: event.clientY - box.top };
  };
  const pointerType = useRef("mouse");
  const onPointerMove = (event: React.PointerEvent) => {
    pointerType.current = event.pointerType;
    if (event.pointerType !== "mouse") return;
    loadNames();
    const point = pointAt(event);
    const index = point ? (rendererRef.current?.pick(point.x, point.y) ?? -1) : -1;
    setHover(index >= 0 && point ? { index, ...point } : null);
  };
  // With a mouse, a click opens the ficha. On a touch screen there is no hover: the first tap
  // shows the municipality and a second tap on it opens the ficha.
  const onClick = (event: React.MouseEvent) => {
    const point = pointAt(event);
    const index = point ? (rendererRef.current?.pick(point.x, point.y) ?? -1) : -1;
    if (index < 0 || !point) {
      setHover(null);
      return;
    }
    if (pointerType.current === "mouse" || hover?.index === index) openFicha(index);
    else {
      loadNames();
      setHover({ index, ...point });
    }
  };
  const largest = () => {
    if (!rows) return 0;
    let best = 0;
    let bestValue = -Infinity;
    rows.forEach((row, i) => {
      const r = reading(row);
      const v = r.kind === "value" ? (r.value ?? -Infinity) : -Infinity;
      if (v > bestValue) {
        bestValue = v;
        best = i;
      }
    });
    return best;
  };
  const onKeyDown = (event: React.KeyboardEvent) => {
    const renderer = rendererRef.current;
    if (!renderer || !rows) return;
    const directions: Record<string, [number, number]> = {
      ArrowRight: [1, 0],
      ArrowLeft: [-1, 0],
      ArrowUp: [0, -1],
      ArrowDown: [0, 1],
    };
    const direction = directions[event.key];
    if (direction) {
      event.preventDefault();
      setHover(null);
      setSelected((current) => (current === null ? largest() : renderer.neighbour(current, ...direction)));
    } else if (event.key === "Enter" && selected !== null) {
      openFicha(selected);
    } else if (event.key === "Escape") {
      setSelected(null);
      setHover(null);
    }
  };
  const onFocus = () => {
    loadNames();
    if (selected === null && rows) setSelected(largest());
  };

  // Escape dismisses the tooltip from anywhere on the page (WCAG 1.4.13).
  useEffect(() => {
    if (hover === null && selected === null) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setHover(null);
        setSelected(null);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [hover, selected]);

  // --- Text of a reading, with its provenance. ---
  const readingText = (r: Reading, withUnit = true) => {
    if (r.kind === "unavailable") return <span>não disponível</span>;
    if (r.kind === "nodata") return <span>sem dado</span>;
    if (r.kind === "zero") return <span>não produziu</span>;
    return (
      <span>
        <span className="num" data-src={r.src}>
          {format(r.value, "int")}
        </span>
        {withUnit ? ` ${unit}` : null}
      </span>
    );
  };
  const SMALL_AREA = "área colhida pequena demais para comparar";
  const yearNum = (year: number) => (
    <span className="num" data-src={yearSrc(year)}>
      {format(year, "year")}
    </span>
  );

  const activeReading = activeRow >= 0 ? reading(activeRow) : null;
  const activeCircle = active !== null && mode === "circles" ? (rendererRef.current?.circleOf(active) ?? null) : null;
  const activeName = activeRow >= 0 && names ? names.municipality_name[activeRow] : undefined;
  const activeUf = activeRow >= 0 && names ? names.state_abbreviation[activeRow] : undefined;
  const tooltipPoint = hover ?? (selected !== null ? (() => {
    const c = rendererRef.current?.point(selected);
    return c ? { x: c[0], y: c[1] } : null;
  })() : null);

  // --- Table rows in the current focus. ---
  const tableRows = useMemo(() => {
    if (!tableOpen || !rows || !names) return [];
    const entries = rows.map((row, i) => ({ row, index: i, reading: reading(row), name: names.municipality_name[row] ?? "" }));
    const collator = new Intl.Collator("pt-BR");
    entries.sort((a, b) => {
      if (sort.key === "name") return (sort.descending ? -1 : 1) * collator.compare(a.name, b.name);
      // Yields from a small area sort below the comparable ones, by value among themselves.
      const key = (r: Reading) =>
        r.kind === "small" ? -1e12 + (r.value ?? 0) : r.kind === "zero" ? -2e12 : (r.value ?? -Infinity);
      const va = key(a.reading);
      const vb = key(b.reading);
      return (sort.descending ? vb - va : va - vb) || collator.compare(a.name, b.name);
    });
    return entries;
  }, [tableOpen, rows, names, reading, sort]);

  const setSeries = (id: string) => {
    const next = series.find((s) => s.id === id);
    if (next) setView((v) => ({ ...v, series: id, year: clampYear(next, v.year) }));
  };
  const legendLabel = (k: number) => {
    const b = (i: number) => (
      <span className="num" data-src={breakSrc(i)}>
        {format(currentBreaks[i], "int")}
      </span>
    );
    if (k === 0) return <>menos de {b(0)}</>;
    if (k === CLASS_COUNT - 1) return <>{b(k - 1)} ou mais</>;
    return (
      <>
        {b(k - 1)}–{b(k)}
      </>
    );
  };
  const measureLabel = MEASURE_LABEL[view.measure](option);
  const circleRefs = scale?.kind === "circles" ? scale.refs : [];
  useFitSelect(seriesSelect, option.phrase);
  useFitSelect(measureSelect, MEASURE_PHRASE[view.measure](option));
  useFitSelect(yearSelect, format(view.year, "year"));
  const focusName = view.uf ? (ufs.find((u) => u.abbr === view.uf)?.name ?? view.uf) : "Brasil";

  return (
    <div className="explore">
      <div className="explore__head">
        {/* Totals ask where; the yield asks how much the crop gives. Same filters in both. */}
        <h1 className="explore__title">
          {isYield ? "Quanto rende" : "Onde se produz"}{" "}
          <span className="explore__term">
            {isYield ? `${option.article}\u00a0` : null}
            <select ref={seriesSelect} aria-label="Cultura" value={view.series} onChange={(e) => setSeries(e.target.value)}>
              {series.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.phrase}
                </option>
              ))}
            </select>
            ,
          </span>{" "}
          <span className="explore__term">
            <select
              ref={measureSelect}
              aria-label="Medida"
              value={view.measure}
              onChange={(e) => setView((v) => ({ ...v, measure: e.target.value as Measure }))}
            >
              {(Object.keys(MEASURE_PHRASE) as Measure[]).map((m) => (
                <option key={m} value={m}>
                  {MEASURE_PHRASE[m](option)}
                </option>
              ))}
            </select>
            ,
          </span>{" "}
          <span className="explore__term">
            em{"\u00a0"}
            <select
              ref={yearSelect}
              aria-label="Ano"
              value={view.year}
              onChange={(e) => setView((v) => ({ ...v, year: Number(e.target.value) }))}
            >
              {years.map((year) => (
                <option key={year} value={year} data-src={yearSrc(year)}>
                  {format(year, "year")}
                </option>
              ))}
            </select>
          </span>
        </h1>
        <p className="explore__hint small">
          Os termos sublinhados são os filtros: clique para trocar a cultura, a medida ou o ano.
        </p>
      </div>

      <div className="explore__body">
        <section className="explore__map-column" aria-label="Mapa dos municípios">
          <div className="explore__toolbar">
            <label className="explore__focus">
              <span className="meta">Foco</span>
              <select
                value={view.uf ?? ""}
                onChange={(e) => setView((v) => ({ ...v, uf: e.target.value || null }))}
              >
                <option value="">Brasil</option>
                {ufs.map((u) => (
                  <option key={u.abbr} value={u.abbr}>
                    {u.name}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="explore__table-toggle"
              aria-expanded={tableOpen}
              aria-controls="explorar-tabela"
              onClick={() => setTableOpen((open) => !open)}
            >
              {tableOpen ? "Ocultar a tabela" : "Ver como tabela"}
            </button>
          </div>

          <div
            ref={wrapRef}
            className="explore__map"
            style={{ aspectRatio: `1 / ${props.aspect}` }}
            role="group"
            aria-roledescription="mapa"
            aria-label={`${measureLabel} por município, ${focusName}. Use as setas para percorrer os municípios e Enter para abrir a ficha; a mesma informação está na tabela.`}
            tabIndex={0}
            onFocus={onFocus}
            onKeyDown={onKeyDown}
            data-view={viewKey}
            data-ready={shown === viewKey ? "true" : "false"}
            data-mode={mode}
            aria-busy={loading}
            data-counts={counts ? JSON.stringify(counts) : undefined}
            data-active-id={activeId}
          >
            <canvas
              ref={canvasRef}
              className="explore__canvas"
              aria-hidden="true"
              onPointerDown={(event) => {
                pointerType.current = event.pointerType;
              }}
              onPointerMove={onPointerMove}
              onPointerLeave={(event) => {
                if (event.pointerType === "mouse") setHover(null);
              }}
              onClick={onClick}
            />
            {active !== null && rendererRef.current && size && (
              <svg
                className="explore__highlight"
                viewBox={`0 0 ${size.width} ${size.height}`}
                aria-hidden="true"
              >
                {mode === "classes" && (
                  <path className="explore__highlight-halo" d={rendererRef.current.svgPath(active)} />
                )}
                <path
                  className={mode === "classes" ? "explore__highlight-line" : "explore__highlight-line explore__highlight-line--thin"}
                  d={rendererRef.current.svgPath(active)}
                />
                {activeCircle && (
                  <>
                    <circle className="explore__highlight-halo" cx={activeCircle.x} cy={activeCircle.y} r={activeCircle.r} />
                    <circle
                      className="explore__highlight-circle"
                      cx={activeCircle.x}
                      cy={activeCircle.y}
                      r={activeCircle.r}
                    />
                  </>
                )}
              </svg>
            )}
            {activeReading && tooltipPoint && (
              <div
                className="explore__tooltip small"
                aria-hidden="true"
                style={{ left: tooltipPoint.x, top: tooltipPoint.y }}
              >
                <span className="explore__tooltip-name">{activeName ?? "…"}</span>
                {activeUf ? <span className="mono"> {activeUf}</span> : null}
                <br />
                {readingText(activeReading)} em {yearNum(view.year)}
                {activeReading.kind === "small" ? (
                  <>
                    <br />
                    <span className="explore__flag">{SMALL_AREA}</span>
                  </>
                ) : null}
              </div>
            )}
            <div className="explore__outline" hidden={!outlineVisible}>
              {props.children}
            </div>
            <p className="explore__loading small" role="status">
              {failed ? (
                "Não foi possível carregar o mapa."
              ) : slowLoading ? (
                <>
                  <span className="explore__loading-bar" aria-hidden="true" />
                  {geometryPending ? "Carregando os municípios…" : "Carregando os dados…"}
                </>
              ) : null}
            </p>
            {valueUnavailable && (
              <p className="explore__status explore__status--note small">
                O valor real da produção só existe a partir de{" "}
                <span
                  className="num"
                  data-src={`${fileOf(option.id, "production_value_real_thousand_brl")}#/years/0|year`}
                >
                  {format(option.valueFirstYear, "year")}
                </span>
                .
              </p>
            )}
          </div>
          <p className="visually-hidden" aria-live="polite">
            {selected !== null && activeReading && activeName ? (
              <>
                {activeName}, {activeUf}: {readingText(activeReading)} em {yearNum(view.year)}
                {activeReading.kind === "small" ? `, ${SMALL_AREA}` : null}
              </>
            ) : null}
          </p>

          <div className="explore__legend">
            <p className="explore__legend-title small">
              {measureLabel}, em {unit}
              {view.measure === "production_value_real_thousand_brl" ? (
                <>
                  {" "}
                  de{" "}
                  <span className="num" data-src={props.baseYear.src}>
                    {props.baseYear.text}
                  </span>
                </>
              ) : null}
            </p>
            {mode === "circles" ? (
              <ul className="legend legend--circles small" aria-label="Legenda do mapa">
                {!valueUnavailable &&
                  circleRefs.map((value, k) => (
                    <li key={value}>
                      <svg
                        className="legend__circle"
                        viewBox="0 0 2 2"
                        style={{ width: `${(200 * circleRadius(value, circleMax, CIRCLE_MAX_RADIUS)) / (MAP_WIDTH + 2 * MAP_PAD)}cqi` }}
                        aria-hidden="true"
                      >
                        <circle cx="1" cy="1" r="0.96" />
                      </svg>
                      <span className="num" data-src={circleSrc(k)}>
                        {format(value, "int")}
                      </span>
                    </li>
                  ))}
                {!valueUnavailable && (
                  <li>
                    <span className="legend__swatch legend__swatch--seq1" aria-hidden="true" />
                    sem círculo: não produziu
                  </li>
                )}
                <li>
                  <span className="legend__swatch legend__swatch--hatch" aria-hidden="true" />
                  {valueUnavailable ? "não disponível" : "sem dado"}
                </li>
              </ul>
            ) : (
              <ul className="legend small" aria-label="Legenda do mapa">
                {Array.from({ length: CLASS_COUNT }, (_, k) => (
                  <li key={k}>
                    <span className={`legend__swatch legend__swatch--seq${k + 2}`} aria-hidden="true" />
                    <span>{legendLabel(k)}</span>
                  </li>
                ))}
                <li>
                  <span className="legend__swatch legend__swatch--seq1" aria-hidden="true" />
                  não produziu
                </li>
                <li>
                  <span className="legend__swatch legend__swatch--dots" aria-hidden="true" />
                  área colhida pequena demais para comparar
                </li>
                <li>
                  <span className="legend__swatch legend__swatch--hatch" aria-hidden="true" />
                  sem dado
                </li>
              </ul>
            )}
            <p className="explore__legend-note small">
              {mode === "circles"
                ? "A área de cada círculo é proporcional ao valor, na mesma escala em todos os anos: os tamanhos podem ser comparados de um ano para outro."
                : "As classes são as mesmas em todos os anos: as cores podem ser comparadas de um ano para outro."}
            </p>
          </div>

          <div className="timeline">
            <button
              type="button"
              className="timeline__play"
              onClick={togglePlay}
              aria-label={playing ? "Pausar a linha do tempo" : "Reproduzir a linha do tempo"}
            >
              <svg viewBox="0 0 16 16" aria-hidden="true">
                {playing ? <path d="M4 3h3v10H4zM9 3h3v10H9z" /> : <path d="M4 2.5v11l9-5.5z" />}
              </svg>
            </button>
            <div className="timeline__track">
              <div className="timeline__labels meta" aria-hidden="true">
                {yearNum(option.firstYear)}
                <span>ano</span>
                {yearNum(option.lastYear)}
              </div>
              <input
                type="range"
                min={0}
                max={years.length - 1}
                value={yearIndex}
                aria-label="Ano"
                aria-valuetext={format(view.year, "year")}
                data-src={yearSrc(view.year)}
                onChange={(e) => setView((v) => ({ ...v, year: option.firstYear + Number(e.target.value) }))}
              />
            </div>
          </div>

          <div className="explore__caption small">
            <p>
              <a href="/metodo/#fontes">Fonte</a>: IBGE, Produção Agrícola Municipal. Municípios sem dado
              aparecem hachurados, e não como zero.
            </p>
            <ul className="explore__links" aria-label="Links do mapa">
              <li>
                <a href={`${dataBase}${measureFiles[0]}`} type="application/json">
                  Dados
                </a>
              </li>
              <li>
                <a href="/metodo/">Método</a>
              </li>
              <li>
                <a href={href || "/explorar/"}>Link</a>
              </li>
            </ul>
          </div>

          {tableOpen && (
            <section id="explorar-tabela" className="explore__table" aria-labelledby="explorar-tabela-titulo">
              <h2 id="explorar-tabela-titulo" className="explore__table-title">
                {measureLabel} por município, {focusName}, {yearNum(view.year)}
              </h2>
              {!names ? (
                <p className="small">Carregando a tabela…</p>
              ) : (
                <div className="table-scroll explore__table-scroll" tabIndex={0} role="region" aria-label="Tabela dos municípios">
                  <table
                    data-src-table="municipalities.json#/municipalities"
                    data-src-cols="municipality_name|text,state_abbreviation|text"
                  >
                    <thead>
                      <tr>
                        <th scope="col" aria-sort={sort.key === "name" ? (sort.descending ? "descending" : "ascending") : "none"}>
                          <button type="button" onClick={() => setSort((s) => ({ key: "name", descending: s.key === "name" ? !s.descending : false }))}>
                            Município
                          </button>
                        </th>
                        <th scope="col">UF</th>
                        <th scope="col" aria-sort={sort.key === "value" ? (sort.descending ? "descending" : "ascending") : "none"}>
                          <button type="button" onClick={() => setSort((s) => ({ key: "value", descending: s.key === "value" ? !s.descending : true }))}>
                            {measureLabel} ({unit})
                          </button>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {tableRows.map((entry) => (
                        <tr key={entry.row} data-row={entry.row}>
                          <th scope="row">
                            <a href={`/municipio/${names.municipality_id[entry.row]}/`}>{entry.name}</a>
                          </th>
                          <td>{names.state_abbreviation[entry.row]}</td>
                          <td className="num">
                            {readingText(entry.reading, false)}
                            {entry.reading.kind === "small" ? (
                              <span className="explore__flag explore__flag--table">área colhida pequena</span>
                            ) : null}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )}
        </section>

        <aside className="explore__panel" aria-label="Painel do Brasil">
          <p className="small">O painel com a série do Brasil e o ranking dos estados entra na próxima etapa.</p>
        </aside>
      </div>
    </div>
  );
}
