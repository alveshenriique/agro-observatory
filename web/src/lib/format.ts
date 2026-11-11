// Number formats of the site, in Brazilian Portuguese. Negative numbers use the minus sign
// (U+2212), as in the charts; percentages come from fractions (-0.09 -> "−9%"), as the data
// contract publishes them.
export type FormatName = "int" | "year" | "pct" | "spct" | "dec2" | "sdec2" | "text" | "date";

export const MINUS = "−";

const integer = new Intl.NumberFormat("pt-BR", {
  maximumFractionDigits: 0,
  useGrouping: "always",
});

function rounded(value: number, digits: number): number {
  const factor = 10 ** digits;
  const result = (Math.sign(value) * Math.round(Math.abs(value) * factor)) / factor;
  return result === 0 ? 0 : result;
}

function withSign(text: string, value: number, signed: boolean): string {
  if (value < 0) return `${MINUS}${text}`;
  return signed && value > 0 ? `+${text}` : text;
}

function asNumber(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new TypeError(`expected a finite number, got ${JSON.stringify(value)}`);
  }
  return value;
}

export function format(value: unknown, name: FormatName): string {
  if (name === "text") return String(value);
  if (name === "date") {
    // The data version ("2026.11.10") or an ISO date ("2026-11-10T00:05:09Z").
    const match = /^(\d{4})[.-](\d{2})[.-](\d{2})/.exec(String(value));
    if (!match) throw new TypeError(`expected a date, got ${JSON.stringify(value)}`);
    return `${match[3]}/${match[2]}/${match[1]}`;
  }
  const n = asNumber(value);
  switch (name) {
    case "int": {
      const r = rounded(n, 0);
      return withSign(integer.format(Math.abs(r)), r, false);
    }
    case "year":
      return String(Math.trunc(n));
    case "pct":
    case "spct": {
      const r = rounded(n * 100, 0);
      return withSign(`${Math.abs(r)}%`, r, name === "spct");
    }
    case "dec2":
    case "sdec2": {
      const r = rounded(n, 2);
      return withSign(Math.abs(r).toFixed(2).replace(".", ","), r, name === "sdec2");
    }
  }
}
