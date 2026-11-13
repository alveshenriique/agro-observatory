// Classes of the Explorar map. One fixed set of classes per series and measure, for the
// whole time series: the quantiles of every positive value of every year pooled together,
// so the map of 1974 and the map of 2025 use the same colours for the same values. The
// data are very concentrated (in soybean production, the top fifth of the municipality-
// years holds about 90% of the output), so equal-count classes spread the municipalities
// over the ramp where equal intervals or natural breaks would push almost all of them into
// the first class. The limits are rounded for a readable legend: on the 1-2-5 scale when the
// values span several orders of magnitude (500 t, 2,000 t, 10,000 t...), with two (then
// three) significant digits when that would merge limits, as in yield.
// Shared by the build (the legend), the browser (the map) and the provenance test, which
// recomputes the limits from the data files.

export const CLASS_COUNT = 5;

export type CellState =
  | { kind: "nodata" }
  | { kind: "zero" }
  | { kind: "value"; value: number; cls: number };

export type Matrix = readonly (readonly (number | null)[])[];

/** Every positive value of a matrix, all years together. */
export function pooledPositives(matrix: Matrix): number[] {
  const out: number[] = [];
  for (const row of matrix) for (const v of row) if (v !== null && v > 0) out.push(v);
  return out;
}

function quantile(sorted: Float64Array, p: number): number {
  const h = (sorted.length - 1) * p;
  const lo = Math.floor(h);
  const hi = Math.ceil(h);
  return (sorted[lo] ?? 0) + (h - lo) * ((sorted[hi] ?? 0) - (sorted[lo] ?? 0));
}

function clean(x: number): number {
  return Number(x.toPrecision(12));
}

function oneTwoFive(x: number): number {
  const k = Math.floor(Math.log10(x));
  const m = x / 10 ** k;
  const best = [1, 2, 5, 10].reduce((a, b) => (Math.abs(Math.log(m / b)) < Math.abs(Math.log(m / a)) ? b : a));
  return clean(best * 10 ** k);
}

function significant(digits: number): (x: number) => number {
  return (x) => {
    const k = Math.floor(Math.log10(x)) - (digits - 1);
    return clean(Math.round(x / 10 ** k) * 10 ** k);
  };
}

const increasing = (xs: number[]) => xs.every((x, i) => x > 0 && (i === 0 || x > (xs[i - 1] ?? 0)));

/** The CLASS_COUNT - 1 class limits of a set of positive values. */
export function classBreaks(values: readonly number[]): number[] {
  if (values.length < CLASS_COUNT) throw new Error("too few positive values to classify");
  const sorted = Float64Array.from(values).sort();
  const raw = Array.from({ length: CLASS_COUNT - 1 }, (_, i) => quantile(sorted, (i + 1) / CLASS_COUNT));
  for (const round of [oneTwoFive, significant(2), significant(3)]) {
    const breaks = raw.map(round);
    if (increasing(breaks)) return breaks;
  }
  return raw.map((x) => Math.round(x));
}

/** Yield in kg/ha from production (t) and harvested area (ha): sum / sum, as the contract asks. */
export function yieldCell(production: number | null, area: number | null): number | null {
  if (production === null || area === null) return null;
  if (area === 0) return production === 0 ? 0 : null;
  return (production / area) * 1000;
}

/**
 * Smallest harvested area (ha) whose yield is compared on the map. Below it the yield is
 * too fragile to class: a few hectares give a yield the municipality often repeats year
 * after year (an estimate more than a measurement), and a tiny crop would paint a huge
 * municipality. Above 100 ha the share of years with exactly last year's yield halves
 * (soybean 30% → 15%, corn 29% → 17%, coffee 31% → 19%), while the municipalities below it
 * hold at most 1.2% of the harvested area of any series. Their yield still shows in the
 * tooltip and the table, flagged; the map gives them a state of their own.
 */
export const MIN_YIELD_AREA_HA = 100;

/** Whether a positive yield comes from too small a harvested area to compare. */
export function isSmallArea(area: number | null): boolean {
  return area !== null && area > 0 && area < MIN_YIELD_AREA_HA;
}

/** The yield of every cell; with `comparableOnly`, the cells of a small area are left out
 *  (null), as the class limits are computed. */
export function yieldMatrix(production: Matrix, area: Matrix, comparableOnly = false): (number | null)[][] {
  return production.map((row, r) =>
    row.map((p, c) => {
      const a = area[r]?.[c] ?? null;
      const y = yieldCell(p, a);
      return comparableOnly && y !== null && y > 0 && isSmallArea(a) ? null : y;
    }),
  );
}

/** No data, zero published, or a value with its class (0 .. CLASS_COUNT - 1). */
export function cellState(value: number | null | undefined, breaks: readonly number[]): CellState {
  if (value === null || value === undefined || !Number.isFinite(value)) return { kind: "nodata" };
  if (value === 0) return { kind: "zero" };
  let cls = 0;
  while (cls < breaks.length && value >= (breaks[cls] ?? Infinity)) cls++;
  return { kind: "value", value, cls };
}
