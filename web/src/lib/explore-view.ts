// The Explorar view (series, measure, year and the state in focus) and its permanent link:
// ?serie=soja&medida=producao&ano=2025&uf=MT. Unknown values fall back to the default and the
// year is kept inside the series' own years, so no coffee view crosses the 2002 unit break.

export const MEASURES = [
  "production_t",
  "harvested_area_ha",
  "planted_or_bearing_area_ha",
  "production_value_real_thousand_brl",
  "yield",
] as const;
export type Measure = (typeof MEASURES)[number];

export const SERIES_SLUG: Record<string, string> = {
  soybean: "soja",
  corn: "milho",
  coffee_processed: "cafe-beneficiado",
  coffee_in_husk: "cafe-em-coco",
  coffee_arabica: "cafe-arabica",
  coffee_canephora: "cafe-canefora",
};

export const MEASURE_SLUG: Record<Measure, string> = {
  production_t: "producao",
  harvested_area_ha: "area-colhida",
  planted_or_bearing_area_ha: "area-plantada",
  production_value_real_thousand_brl: "valor",
  yield: "rendimento",
};

export interface SeriesRange {
  id: string;
  firstYear: number;
  lastYear: number;
}

export interface ExploreView {
  series: string;
  measure: Measure;
  year: number;
  uf: string | null;
}

const invert = <T extends string>(map: Record<T, string>) =>
  Object.fromEntries(Object.entries(map).map(([k, v]) => [v, k])) as Record<string, T>;
const SERIES_BY_SLUG = invert(SERIES_SLUG);
const MEASURE_BY_SLUG = invert(MEASURE_SLUG);

export function clampYear(range: SeriesRange, year: number): number {
  return Math.min(range.lastYear, Math.max(range.firstYear, year));
}

export function parseView(
  search: string,
  series: readonly SeriesRange[],
  ufs: readonly string[],
  fallback: ExploreView,
): ExploreView {
  const params = new URLSearchParams(search);
  const seriesId = SERIES_BY_SLUG[params.get("serie") ?? ""] ?? fallback.series;
  const range = series.find((s) => s.id === seriesId) ?? series.find((s) => s.id === fallback.series);
  if (!range) throw new Error("no series to explore");
  const measure = MEASURE_BY_SLUG[params.get("medida") ?? ""] ?? fallback.measure;
  const rawYear = Number(params.get("ano"));
  const year = clampYear(range, Number.isInteger(rawYear) && rawYear > 0 ? rawYear : fallback.year);
  const uf = (params.get("uf") ?? "").toUpperCase();
  return { series: range.id, measure, year, uf: ufs.includes(uf) ? uf : null };
}

export function serializeView(view: ExploreView): string {
  const params = new URLSearchParams({
    serie: SERIES_SLUG[view.series] ?? view.series,
    medida: MEASURE_SLUG[view.measure],
    ano: String(view.year),
  });
  if (view.uf) params.set("uf", view.uf);
  return `?${params.toString()}`;
}
