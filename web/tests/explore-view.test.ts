import { type ExploreView, parseView, serializeView } from "../src/lib/explore-view";

const series = [
  { id: "soybean", firstYear: 1974, lastYear: 2025 },
  { id: "coffee_in_husk", firstYear: 1974, lastYear: 2001 },
  { id: "coffee_processed", firstYear: 2002, lastYear: 2025 },
];
const ufs = ["MT", "PR"];
const fallback: ExploreView = { series: "soybean", measure: "production_t", year: 2025, uf: null };

describe("Explorar view in the URL", () => {
  it("round-trips through a readable query string", () => {
    const view: ExploreView = { series: "coffee_processed", measure: "yield", year: 2010, uf: "PR" };
    const search = serializeView(view);
    expect(search).toBe("?serie=cafe-beneficiado&medida=rendimento&ano=2010&uf=PR");
    expect(parseView(search, series, ufs, fallback)).toEqual(view);
  });

  it("falls back to the default for anything unknown", () => {
    expect(parseView("?serie=trigo&medida=preco&ano=abc&uf=XX", series, ufs, fallback)).toEqual(fallback);
    expect(parseView("", series, ufs, fallback)).toEqual(fallback);
  });

  it("keeps the year inside the series, so coffee never crosses the 2002 break", () => {
    expect(parseView("?serie=cafe-em-coco&ano=2025", series, ufs, fallback).year).toBe(2001);
    expect(parseView("?serie=cafe-beneficiado&ano=1990", series, ufs, fallback).year).toBe(2002);
  });
});
