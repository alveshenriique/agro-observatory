import {
  CIRCLE_MAX_RADIUS,
  circleRadius,
  circleScale,
  drawOrder,
  floorOneTwoFive,
} from "../src/lib/symbols";

describe("proportional circles", () => {
  it("make the area, not the radius, proportional to the value", () => {
    const max = 2_360_926;
    const big = circleRadius(max, max, CIRCLE_MAX_RADIUS);
    const quarter = circleRadius(max / 4, max, CIRCLE_MAX_RADIUS);
    expect(big).toBe(CIRCLE_MAX_RADIUS);
    expect(quarter).toBeCloseTo(CIRCLE_MAX_RADIUS / 2, 10);
    expect((Math.PI * quarter ** 2) / (Math.PI * big ** 2)).toBeCloseTo(0.25, 10);
  });

  it("draw no circle for zero or missing values, and hold tiny ones at the minimum", () => {
    expect(circleRadius(0, 100, 24, 1)).toBe(0);
    expect(circleRadius(Number.NaN, 100, 24, 1)).toBe(0);
    expect(circleRadius(0.0001, 100, 24, 1)).toBe(1);
    expect(circleRadius(100, 100, 24, 1)).toBe(24);
  });

  it("scale every year with the largest value of the series and round the legend", () => {
    const scale = circleScale([5750, 12_000, 2_360_926, 0.5]);
    expect(scale.max).toBe(2_360_926);
    expect(scale.refs).toEqual([2_000_000, 200_000, 50_000]);
    for (const ref of scale.refs) expect(ref).toBeLessThanOrEqual(scale.max);
  });

  it("round down on the 1-2-5 scale", () => {
    expect([0.7, 1, 1.9, 2, 4.99, 5, 9.99, 10, 472_185].map(floorOneTwoFive)).toEqual([
      0.5, 1, 1, 2, 2, 5, 5, 10, 200_000,
    ]);
    expect(() => floorOneTwoFive(0)).toThrow();
  });

  it("draw the larger circles first, so the smaller ones stay on top", () => {
    expect([...drawOrder([2, 0, 5, 1, 5])]).toEqual([2, 4, 0, 3]);
  });
});
