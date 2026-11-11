import { render } from "@testing-library/react";

import AnomalyBars, { barLabel } from "../src/components/charts/AnomalyBars";
import { MINUS } from "../src/lib/format";

const bars = [
  { row: 10, year: 2004, anomaly: 0.12, deficit: false },
  { row: 11, year: 2005, anomaly: -0.6598, deficit: true },
  { row: 13, year: 2007, anomaly: 0.05, deficit: false },
];

function renderChart() {
  return render(
    <AnomalyBars
      label="Teste: rendimento em relação à tendência"
      bars={bars}
      missingYears={[2006]}
      years={[2004, 2007]}
      extent={[-0.7, 0.44]}
      deficitLabel="seca na floração e enchimento"
      table="analysis.json#/climate_yield_by_state"
      cols="harvest_year|year,yield_anomaly|spct"
      variant="focus"
      yTicks={[
        { value: 0, text: "0%", src: "a.json#/x!within|spct", carried: "0" },
        { value: -0.4, text: `${MINUS}40%`, src: "a.json#/x!within|spct", carried: "-0.4" },
      ]}
      annotate={[bars[1]!]}
    />,
  );
}

describe("AnomalyBars", () => {
  it("draws one bar per year with data, coloured by class, citing its row", () => {
    const { container } = renderChart();
    const rects = container.querySelectorAll(".bar");
    expect(rects).toHaveLength(3);
    expect([...rects].map((rect) => rect.getAttribute("data-row"))).toEqual(["10", "11", "13"]);
    expect(rects[1]?.classList.contains("bar--deficit")).toBe(true);
    expect(rects[1]?.classList.contains("bar--down")).toBe(true);
    expect(rects[0]?.classList.contains("bar--other")).toBe(true);
    const chart = container.querySelector("[data-chart]");
    expect(chart?.getAttribute("data-src-table")).toBe("analysis.json#/climate_yield_by_state");
  });

  it("names every bar and keeps exactly one in the tab order", () => {
    const { container } = renderChart();
    const rects = [...container.querySelectorAll(".bar")];
    expect(rects[1]?.getAttribute("aria-label")).toBe(
      `2005: ${MINUS}66% em relação à tendência, seca na floração e enchimento`,
    );
    expect(rects.filter((rect) => rect.getAttribute("tabindex") === "0")).toHaveLength(1);
    expect(barLabel(bars[0]!, "seca")).toBe("2004: +12% em relação à tendência");
  });

  it("marks years without data apart from zero", () => {
    const { container } = renderChart();
    expect(container.querySelectorAll(".anomaly-chart__missing")).toHaveLength(1);
  });

  it("prints ticks and annotations with their provenance", () => {
    const { container } = renderChart();
    const ticks = [...container.querySelectorAll(".anomaly-chart__y span")];
    expect(ticks.map((tick) => [tick.textContent, tick.getAttribute("data-value")])).toEqual([
      ["0%", "0"],
      [`${MINUS}40%`, "-0.4"],
    ]);
    const note = container.querySelector(".note");
    expect(note?.textContent).toBe(`2005 ${MINUS}66%`);
    expect(note?.getAttribute("data-row")).toBe("11");
  });
});
