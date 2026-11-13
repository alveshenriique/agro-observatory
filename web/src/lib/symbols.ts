// Proportional circles of the Explorar map, for the totals (production, areas and value).
// A choropleth of a total paints each municipality whole, so the eye reads the painted area
// and not the value: huge municipalities with an average output take over the map, and
// regions of small, very productive ones vanish. A circle at each municipality, with its
// AREA proportional to the value (radius ∝ √value), shows the amount wherever it is.
//
// One scale per series and measure for the whole time series, like the colour classes: the
// largest value of any year gets the largest radius, so circle sizes compare across years.
// The scale is in map units (the national map is 1,000 units wide), so the same value has
// the same size on the map and in the legend at any screen width, and keeps the national
// size when a state is in focus. Below a minimum the radius is held at 0.75 CSS px, so
// that every municipality that produced shows: under it the area stops being
// proportional, which only touches circles too small to compare by eye anyway.
// Shared by the build (the legend), the browser (the map) and the provenance test.

/** Radius of the largest value of the series, in map units. */
export const CIRCLE_MAX_RADIUS = 24;
/** Smallest radius drawn, in CSS pixels. */
export const CIRCLE_MIN_RADIUS_PX = 0.75;

export interface CircleScale {
  /** Largest value of any year: it gets CIRCLE_MAX_RADIUS. */
  max: number;
  /** Reference values for the legend, largest first, on the 1-2-5 scale. */
  refs: number[];
}

/** Largest number of the form 1, 2 or 5 × 10^k not above x. */
export function floorOneTwoFive(x: number): number {
  if (!(x > 0)) throw new RangeError(`expected a positive number, got ${x}`);
  const power = 10 ** Math.floor(Math.log10(x));
  const leading = x / power;
  const step = leading >= 5 ? 5 : leading >= 2 ? 2 : 1;
  return Number((step * power).toPrecision(12));
}

/** The scale of a set of positive values (all years pooled): the maximum and three round
 *  references at about the maximum, a fifth and a twenty-fifth of it (radii 1 : 0.45 : 0.2). */
export function circleScale(values: readonly number[]): CircleScale {
  let max = 0;
  for (const v of values) if (v > max) max = v;
  if (!(max > 0)) throw new RangeError("no positive value to scale the circles");
  return { max, refs: [max, max / 5, max / 25].map(floorOneTwoFive) };
}

/** Radius of a value, in the units of `maxRadius`; 0 means no circle. */
export function circleRadius(value: number, max: number, maxRadius: number, minRadius = 0): number {
  if (!(value > 0)) return 0;
  return Math.max(minRadius, maxRadius * Math.sqrt(value / max));
}

/** Drawing order: the indexes with a circle, largest first, so smaller circles sit on top. */
export function drawOrder(radii: ArrayLike<number>): Int32Array {
  const indexes: number[] = [];
  for (let i = 0; i < radii.length; i++) if ((radii[i] ?? 0) > 0) indexes.push(i);
  indexes.sort((a, b) => (radii[b] ?? 0) - (radii[a] ?? 0) || a - b);
  return Int32Array.from(indexes);
}
