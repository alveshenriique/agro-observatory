// Browser-side loading of the data package for the Explorar island: each file is fetched
// once and shared. Paths are relative to the pinned data version.
import type { GeoTopoJson } from "../../types/data/topology";

import { type DecodeOptions, decodeTopology, type Frame, type MapGeometry, stateOf } from "./geometry";
import { pause } from "./map-renderer";

export interface ExploreFile {
  series: string;
  measure: string;
  unit_pt: string;
  years: number[];
  values: (number | null)[][];
}

export interface Municipalities {
  municipalities: {
    municipality_id: number[];
    municipality_name: string[];
    state_abbreviation: string[];
  };
}

export interface Geo {
  geometry: MapGeometry;
  ids: number[];
  /** Thin borders between municipalities, only when zoomed into a state. */
  thinBorders: boolean;
}

const cache = new Map<string, Promise<unknown>>();

export function fetchJson<T>(base: string, file: string): Promise<T> {
  const url = `${base}${file}`;
  if (!cache.has(url)) {
    cache.set(
      url,
      fetch(url).then((response) => {
        if (!response.ok) throw new Error(`${file}: HTTP ${response.status}`);
        return response.json();
      }),
    );
  }
  return cache.get(url) as Promise<T>;
}

const decoded = new Map<string, Promise<Geo>>();

/** A mesh, fetched and decoded once however many times it is asked for. */
function load(base: string, file: string, options: DecodeOptions): Promise<Geo> {
  const url = `${base}${file}`;
  let geo = decoded.get(url);
  if (!geo) {
    geo = fetchJson<GeoTopoJson>(base, file).then(async (topo) => {
      performance.mark(`atlas:mesh-decode:${file}`);
      const geometry = await decodeTopology(topo, "municipalities", { ...options, pause });
      performance.measure("atlas:mesh-decode", `atlas:mesh-decode:${file}`);
      return { geometry, ids: geometry.ids, thinBorders: !options.borderGroup };
    });
    decoded.set(url, geo);
  }
  return geo;
}

/** The national mesh: municipalities, state borders and the country outline, in the frame
 *  the page was built with (so it lands exactly on the outline drawn before it). */
export function loadNational(base: string, frame: Frame): Promise<Geo> {
  return load(base, "geo/municipalities.topo.json", { borderGroup: stateOf, frame });
}

/** The detailed mesh of one state, loaded when the state comes into focus. */
export function loadState(base: string, uf: string): Promise<Geo> {
  return load(base, `geo/state/${uf}.topo.json`, {});
}

/** Row of a municipality in the canonical order (ascending IBGE code) of every matrix. */
export function rowsOf(ids: number[], canonical: number[]): number[] {
  return ids.map((id) => {
    let lo = 0;
    let hi = canonical.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const value = canonical[mid] ?? 0;
      if (value === id) return mid;
      if (value < id) lo = mid + 1;
      else hi = mid - 1;
    }
    return -1;
  });
}
