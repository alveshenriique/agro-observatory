// Build-time view model of the Análise page, read from analysis.json, catalog.json and
// municipalities.json. It selects and orders rows; every number it hands to the page keeps
// the row it came from, so the markup can cite it (lib/provenance.ts).
import type { AnalysisJson } from "../types/data/analysis";
import type { MunicipalitiesJson } from "../types/data/municipalities";
import { loadCatalog, loadDataFile } from "./data";

export const TABLE = "analysis.json#/climate_yield_by_state";
export const SUMMARY = "analysis.json#/climate_summary_by_state";
export const BAR_COLUMNS = "harvest_year|year,yield_anomaly|spct";

export interface AnomalyBar {
  row: number;
  year: number;
  anomaly: number;
  deficit: boolean;
}

export interface StatePanel {
  abbreviation: string;
  name: string;
  summaryRow: number;
  bars: AnomalyBar[];
  missingYears: number[];
}

export interface AnalysisModel {
  crop: string;
  firstYear: number;
  lastYear: number;
  extent: [number, number];
  deficitLabel: string;
  focus: StatePanel;
  panels: StatePanel[];
}

// The state of the opening figure: the one where water balance and yield move together the
// most (highest correlation), Rio Grande do Sul in the current data.
function byCorrelation(a: StatePanel, b: StatePanel, corr: (number | null)[]): number {
  return (corr[b.summaryRow] ?? -Infinity) - (corr[a.summaryRow] ?? -Infinity);
}

export function analysisModel(): AnalysisModel {
  const analysis = loadDataFile<AnalysisJson>("analysis.json");
  const places = loadDataFile<MunicipalitiesJson>("municipalities.json");
  const catalog = loadCatalog();
  const { headline } = analysis;
  // The page is the finding: without it (the CI sample has no climate normal) the build
  // must fail rather than print an empty page.
  if (!headline || headline.first_year === null || headline.last_year === null) {
    throw new Error("analysis.json has no headline; the Análise page cannot be built");
  }
  const { first_year: firstYear, last_year: lastYear } = headline;
  const t = analysis.climate_yield_by_state;
  const s = analysis.climate_summary_by_state;
  const crop = headline.crop;
  const deficitLabel = catalog.climate_labels[crop]?.is_water_deficit;
  if (!deficitLabel) throw new Error(`catalog.json has no water-deficit label for ${crop}`);

  // The same state-years as the headline: a climate normal, a yield trend and an anomaly.
  const bars = new Map<string, AnomalyBar[]>();
  for (let row = 0; row < t.harvest_year.length; row++) {
    const anomaly = t.yield_anomaly[row];
    if (
      t.crop[row] !== crop ||
      !t.is_normal_available[row] ||
      !t.is_trend_available[row] ||
      anomaly === null ||
      anomaly === undefined
    ) {
      continue;
    }
    const state = t.territory_name[row] as string;
    const list = bars.get(state) ?? [];
    list.push({
      row,
      year: t.harvest_year[row] as number,
      anomaly,
      deficit: t.is_water_deficit[row] === true,
    });
    bars.set(state, list);
  }

  const names = new Map(
    places.states.state_abbreviation.map((abbreviation, i) => [
      abbreviation,
      places.states.state_name[i] as string,
    ]),
  );
  const years: number[] = [];
  for (let year = firstYear; year <= lastYear; year++) years.push(year);

  const panels: StatePanel[] = [];
  for (const [abbreviation, list] of bars) {
    const summaryRow = s.territory_name.findIndex(
      (name, i) => name === abbreviation && s.crop[i] === crop,
    );
    if (summaryRow < 0) throw new Error(`no climate summary for ${abbreviation}`);
    list.sort((a, b) => a.year - b.year);
    const present = new Set(list.map((bar) => bar.year));
    panels.push({
      abbreviation,
      name: names.get(abbreviation) ?? abbreviation,
      summaryRow,
      bars: list,
      missingYears: years.filter((year) => !present.has(year)),
    });
  }
  panels.sort((a, b) => byCorrelation(a, b, s.corr_water_balance_yield));
  const all = panels.flatMap((panel) => panel.bars.map((bar) => bar.anomaly));
  const focus = panels[0];
  if (!focus) throw new Error("no state with climate and yield");

  return {
    crop,
    firstYear,
    lastYear,
    extent: [Math.min(...all), Math.max(...all)],
    deficitLabel,
    focus,
    panels,
  };
}

/** The `count` most negative anomalies of a panel, most negative first. */
export function worstYears(panel: StatePanel, count: number): AnomalyBar[] {
  return [...panel.bars].sort((a, b) => a.anomaly - b.anomaly).slice(0, count);
}
