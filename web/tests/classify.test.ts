import {
  CLASS_COUNT,
  cellState,
  classBreaks,
  isSmallArea,
  MIN_YIELD_AREA_HA,
  pooledPositives,
  yieldCell,
  yieldMatrix,
} from "../src/lib/classify";
import { parseRef, resolveRef, siblingFile } from "../src/lib/provenance";
import { circleScale } from "../src/lib/symbols";

// A long-tailed sample, like municipal production: many small values, a few huge ones.
const skewed = Array.from({ length: 1000 }, (_, i) => Math.round(1.02 ** i));

describe("class limits", () => {
  it("are CLASS_COUNT - 1 increasing limits on the 1-2-5 scale for spread-out data", () => {
    const breaks = classBreaks(skewed);
    expect(breaks).toHaveLength(CLASS_COUNT - 1);
    expect(breaks).toEqual([...breaks].sort((a, b) => a - b));
    for (const b of breaks) {
      const mantissa = b / 10 ** Math.floor(Math.log10(b));
      expect([1, 2, 5]).toContain(mantissa);
    }
  });

  it("fall back to significant digits when 1-2-5 would merge limits", () => {
    const yields = Array.from({ length: 500 }, (_, i) => 1500 + i * 4); // 1,500 to 3,496
    const breaks = classBreaks(yields);
    expect(new Set(breaks).size).toBe(CLASS_COUNT - 1);
    expect(breaks).toEqual([1900, 2300, 2700, 3100]);
  });

  it("pool every positive value of every year, leaving out zeros and missing data", () => {
    expect(pooledPositives([[null, 0, 3], [5, null, 0]])).toEqual([3, 5]);
  });
});

describe("cell states", () => {
  const breaks = [500, 2000, 10000, 50000];
  it("keep no data, zero and values apart", () => {
    expect(cellState(null, breaks)).toEqual({ kind: "nodata" });
    expect(cellState(0, breaks)).toEqual({ kind: "zero" });
    expect(cellState(499, breaks)).toEqual({ kind: "value", value: 499, cls: 0 });
    expect(cellState(500, breaks)).toEqual({ kind: "value", value: 500, cls: 1 });
    expect(cellState(60000, breaks)).toEqual({ kind: "value", value: 60000, cls: 4 });
  });
});

describe("yield", () => {
  it("is production / harvested area in kg/ha, never a zero for missing data", () => {
    expect(yieldCell(3000, 1000)).toBe(3000);
    expect(yieldCell(0, 0)).toBe(0);
    expect(yieldCell(5, 0)).toBeNull();
    expect(yieldCell(null, 10)).toBeNull();
    expect(yieldMatrix([[10, null]], [[5, 5]])).toEqual([[2000, null]]);
  });
});

describe("map references", () => {
  const production = { values: [[1000, 0], [null, 3000]] };
  const area = { values: [[500, 0], [100, 1000]] };

  it("resolve the yield of a cell from production and the sibling area file", () => {
    const ref = parseRef("explore/soybean/production_t.json#/values/1/1!yield|int");
    expect(siblingFile(ref)).toBe("explore/soybean/harvested_area_ha.json");
    expect(resolveRef(ref, production, null, area)).toBe(3000);
    expect(() => resolveRef(ref, production)).toThrow(/needs/);
  });

  it("resolve the circle references of a matrix and the class limits of the yield", () => {
    const matrix = { values: [skewed] };
    const { refs } = circleScale(skewed);
    expect(resolveRef(parseRef("explore/x/production_t.json#/values!circle:1|int"), matrix)).toBe(refs[1]);
    expect(() => parseRef("explore/x/production_t.json#/values!circle|int")).toThrow(/needs an argument/);
    expect(() => resolveRef(parseRef("explore/x/production_t.json#/values!circle:3|int"), matrix)).toThrow(
      /no value 3/,
    );
    const prod = { values: [skewed] };
    const area = { values: [skewed.map(() => 200)] };
    const yields = classBreaks(skewed.map((v) => (v / 200) * 1000));
    expect(resolveRef(parseRef("explore/x/production_t.json#/values!ybreak:0|int"), prod, null, area)).toBe(yields[0]);
    // Municipalities with a harvested area too small to compare do not move the limits.
    const withSmall = { values: [[...skewed, 1e9, 1e9, 1e9]] };
    const areaWithSmall = { values: [[...skewed.map(() => 200), 5, 5, 5]] };
    expect(resolveRef(parseRef("explore/x/production_t.json#/values!ybreak:3|int"), withSmall, null, areaWithSmall)).toBe(
      yields[3],
    );
  });

  it("flag a positive yield from a harvested area under the minimum", () => {
    expect(isSmallArea(MIN_YIELD_AREA_HA - 1)).toBe(true);
    expect(isSmallArea(MIN_YIELD_AREA_HA)).toBe(false);
    expect(isSmallArea(0)).toBe(false);
    expect(isSmallArea(null)).toBe(false);
    const matrix = yieldMatrix([[10, 10, 0]], [[50, 500, 50]], true);
    expect(matrix).toEqual([[null, 20, 0]]);
  });
});
