// Keyboard and pointer access to the bars of every chart. One bar per chart sits in the tab
// order (roving tabindex); the arrows, Home and End move between years and the tooltip
// repeats the focused bar's accessible name. The tooltip stays while the pointer is over the
// chart and Esc dismisses it (WCAG 1.4.13). It cites the same table row as its bar, so the
// provenance test also covers it. Without JavaScript the bars stay readable and the table
// under the figure has every value.
const STEP: Record<string, number> = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
// The same tokens as lib/provenance.ts numberTokens: numbers go in the mono, words in the sans.
const NUMBER = /([−+]?\d+(?:[.,]\d+)*%?)/u;

function sentence(text: string): Node[] {
  return text.split(NUMBER).map((part, i) => {
    if (i % 2 === 0) return document.createTextNode(part);
    const number = document.createElement("span");
    number.className = "num";
    number.textContent = part;
    return number;
  });
}

function setup(chart: HTMLElement): void {
  const bars = Array.from(chart.querySelectorAll<SVGRectElement>(".bar"));
  const plot = chart.querySelector<HTMLElement>(".anomaly-chart__plot");
  const tooltip = chart.querySelector<HTMLElement>(".chart-tooltip");
  if (!plot || !tooltip || bars.length === 0) return;

  const hide = () => {
    tooltip.hidden = true;
    delete tooltip.dataset.row;
  };

  const show = (bar: SVGRectElement) => {
    tooltip.replaceChildren(...sentence(bar.getAttribute("aria-label") ?? ""));
    if (bar.dataset.row !== undefined) tooltip.dataset.row = bar.dataset.row;
    tooltip.hidden = false;
    const area = plot.getBoundingClientRect();
    const box = bar.getBoundingClientRect();
    const half = tooltip.offsetWidth / 2;
    const centre = box.left + box.width / 2 - area.left;
    tooltip.style.left = `${Math.min(Math.max(centre, half), area.width - half)}px`;
    tooltip.style.top = `${box.top - area.top}px`;
  };

  bars.forEach((bar, index) => {
    bar.addEventListener("focus", () => show(bar));
    bar.addEventListener("blur", hide);
    bar.addEventListener("pointerenter", () => show(bar));
    bar.addEventListener("keydown", (event) => {
      let next: number;
      if (event.key in STEP) next = index + (STEP[event.key] ?? 0);
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = bars.length - 1;
      else if (event.key === "Escape") return hide();
      else return;
      event.preventDefault();
      const target = bars[Math.max(0, Math.min(bars.length - 1, next))];
      if (!target || target === bar) return;
      bar.tabIndex = -1;
      target.tabIndex = 0;
      target.focus();
    });
  });
  plot.addEventListener("pointerleave", () => {
    if (!bars.some((bar) => bar === document.activeElement)) hide();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !tooltip.hidden) hide();
  });
}

for (const chart of document.querySelectorAll<HTMLElement>("[data-chart]")) setup(chart);
