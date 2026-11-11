// Yield anomaly by harvest year, one bar per year, water-deficit years in the dry colour.
// Rendered at build time (no client directive): the SVG draws only bars and lines and
// stretches to any width (preserveAspectRatio="none", non-scaling strokes), while ticks,
// annotations and the tooltip are HTML placed in percentages, so the text keeps its size on
// a phone and on the 1,240 px layout. Every printed number carries its provenance: the bars
// cite their row of the table (data-row + data-src-table/cols), the ticks their column.
import { range } from "d3-array";
import { scaleBand, scaleLinear } from "d3-scale";
import type { CSSProperties } from "react";

import type { AnomalyBar } from "../../lib/analysis";
import { format } from "../../lib/format";

export interface TickLabel {
  value: number;
  text: string;
  src: string;
  carried: string;
}

export interface AnomalyBarsProps {
  label: string;
  bars: AnomalyBar[];
  missingYears: number[];
  years: [number, number];
  extent: [number, number];
  deficitLabel: string;
  table: string;
  cols: string;
  variant: "focus" | "panel";
  yTicks?: TickLabel[];
  xTicks?: TickLabel[];
  annotate?: AnomalyBar[];
}

// padBottom leaves room under the lowest bar for its annotation.
const SIZE = {
  focus: { width: 1000, height: 340, padTop: 12, padBottom: 44 },
  panel: { width: 350, height: 96, padTop: 4, padBottom: 4 },
} as const;

export function barLabel(bar: AnomalyBar, deficitLabel: string): string {
  const head = `${format(bar.year, "year")}: ${format(bar.anomaly, "spct")} em relação à tendência`;
  return bar.deficit ? `${head}, ${deficitLabel}` : head;
}

export function layout(props: Pick<AnomalyBarsProps, "years" | "extent" | "variant">) {
  const { width, height, padTop, padBottom } = SIZE[props.variant];
  const x = scaleBand<number>()
    .domain(range(props.years[0], props.years[1] + 1))
    .range([0, width])
    .paddingInner(0.14)
    .paddingOuter(0.05);
  const y = scaleLinear()
    .domain([Math.min(props.extent[0], 0), Math.max(props.extent[1], 0)])
    .range([height - padBottom, padTop]);
  return { x, y, width, height, zero: y(0) };
}

const pct = (value: number, total: number) => `${((value / total) * 100).toFixed(3)}%`;

export default function AnomalyBars(props: AnomalyBarsProps) {
  const { x, y, width, height, zero } = layout(props);
  const band = x.bandwidth();
  const missingHeight = height * 0.06;

  return (
    <div
      className={`anomaly-chart anomaly-chart--${props.variant}`}
      data-chart=""
      data-animate=""
      data-src-table={props.table}
      data-src-cols={props.cols}
    >
      {props.yTicks && (
        <div className="anomaly-chart__y meta" aria-hidden="true">
          {props.yTicks.map((tick) => (
            <span
              key={tick.carried}
              style={{ top: pct(y(tick.value), height) }}
              data-src={tick.src}
              data-value={tick.carried}
            >
              {tick.text}
            </span>
          ))}
        </div>
      )}
      <div className="anomaly-chart__plot">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="none"
          role="group"
          aria-label={props.label}
        >
          {props.yTicks?.map((tick) => (
            <line
              key={tick.carried}
              className={tick.value === 0 ? "anomaly-chart__zero" : "anomaly-chart__grid"}
              x1={0}
              x2={width}
              y1={y(tick.value)}
              y2={y(tick.value)}
              vectorEffect="non-scaling-stroke"
            />
          ))}
          {!props.yTicks && (
            <line
              className="anomaly-chart__zero"
              x1={0}
              x2={width}
              y1={zero}
              y2={zero}
              vectorEffect="non-scaling-stroke"
            />
          )}
          {props.missingYears.map((year) => (
            <rect
              key={`missing-${year}`}
              className="anomaly-chart__missing"
              x={x(year)}
              y={zero - missingHeight / 2}
              width={band}
              height={missingHeight}
              vectorEffect="non-scaling-stroke"
              aria-hidden="true"
            />
          ))}
          {props.bars.map((bar, i) => {
            const end = y(bar.anomaly);
            return (
              <rect
                key={bar.row}
                className={`bar ${bar.deficit ? "bar--deficit" : "bar--other"} ${
                  bar.anomaly < 0 ? "bar--down" : "bar--up"
                }`}
                x={x(bar.year)}
                y={Math.min(end, zero)}
                width={band}
                height={Math.max(Math.abs(end - zero), 0.5)}
                vectorEffect="non-scaling-stroke"
                style={{ "--i": i } as CSSProperties}
                role="img"
                tabIndex={i === 0 ? 0 : -1}
                aria-label={barLabel(bar, props.deficitLabel)}
                data-row={bar.row}
              />
            );
          })}
        </svg>
        {props.annotate && (
          <div className="anomaly-chart__notes meta" aria-hidden="true">
            {props.annotate.map((bar) => {
              const centre = (x(bar.year) ?? 0) + band / 2;
              // Near the edges the label hangs inwards instead of centring on the bar.
              const anchor =
                centre < width * 0.12 ? "start" : centre > width * 0.88 ? "end" : "middle";
              return (
                <span
                  key={bar.row}
                  className={`note note--${anchor}`}
                  data-row={bar.row}
                  style={{
                    left: pct(centre, width),
                    top: pct(Math.max(y(bar.anomaly), zero), height),
                  }}
                >
                  {format(bar.year, "year")} {format(bar.anomaly, "spct")}
                </span>
              );
            })}
          </div>
        )}
        <div className="chart-tooltip small" hidden aria-hidden="true" />
      </div>
      {props.xTicks && (
        <div className="anomaly-chart__x meta" aria-hidden="true">
          {props.xTicks.map((tick) => (
            <span
              key={tick.carried}
              style={{ left: pct((x(tick.value) ?? 0) + band / 2, width) }}
              data-src={tick.src}
              data-value={tick.carried}
            >
              {tick.text}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
