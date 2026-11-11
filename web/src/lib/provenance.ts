// Provenance of every number the site prints. No number is typed by hand: each one is a
// reference into a file of the data package, written next to it in the markup, and the
// end-to-end test re-reads the referenced files and checks that the page shows exactly
// what they say (e2e/provenance.ts).
//
// A reference is `file#/json/pointer[!op[:argument]]|format`; several are joined with ";":
//   analysis.json#/headline/below_trend_share_all_years|pct     -> "43%"
//   catalog.json#/series/last_year!max|year                     -> "2025"
//   analysis.json#/climate_summary_by_state/crop!count:soybean|int -> "16"
// Operations: max, min, sum and count over an array (count with an argument counts the
// items equal to it); `year` takes the year in parentheses
// of a citation ("(2022)"); `within` and `member` check a value carried by the element
// itself (data-value), for axis ticks: within the range of the plotted column, or one of
// its values.
// Markup: `data-src` holds the references; rows of a columnar table use `data-row` on the
// element and `data-src-table` + `data-src-cols` ("col|format,col|format") on an ancestor.
// This module is shared by the build (Node) and the test runner, so it never touches the
// file system or the DOM.
import { format, type FormatName } from "./format";

export type Op = "max" | "min" | "sum" | "count" | "year" | "within" | "member";

export interface Ref {
  file: string;
  pointer: string;
  op?: Op;
  arg?: string;
  format: FormatName;
}

const OPS = new Set<string>(["max", "min", "sum", "count", "year", "within", "member"]);
const FORMATS = new Set<string>(["int", "year", "pct", "spct", "dec2", "sdec2", "text", "date"]);

export function serializeRef(ref: Ref): string {
  const op = ref.op ? `!${ref.op}${ref.arg !== undefined ? `:${ref.arg}` : ""}` : "";
  return `${ref.file}#${ref.pointer}${op}|${ref.format}`;
}

export function parseRef(text: string): Ref {
  const match = /^([\w.-]+\.json)#(\/[^!|]*)(?:!(\w+)(?::([\w-]+))?)?\|(\w+)$/.exec(text.trim());
  if (!match) throw new Error(`malformed reference: ${text}`);
  const file = match[1] as string;
  const pointer = match[2] as string;
  const op = match[3];
  const arg = match[4];
  const fmt = match[5] as string;
  if (op !== undefined && !OPS.has(op)) throw new Error(`unknown operation in ${text}`);
  if (arg !== undefined && op !== "count") throw new Error(`only count takes an argument: ${text}`);
  if (!FORMATS.has(fmt)) throw new Error(`unknown format in ${text}`);
  const ref: Ref = { file, pointer, format: fmt as FormatName };
  if (op !== undefined) ref.op = op as Op;
  if (arg !== undefined) ref.arg = arg;
  return ref;
}

export function parseRefs(text: string): Ref[] {
  return text
    .split(";")
    .filter((part) => part.trim() !== "")
    .map(parseRef);
}

/** References for one row of a columnar table (data-src-table + data-src-cols + data-row). */
export function rowRefs(table: string, cols: string, row: number): Ref[] {
  return cols.split(",").map((spec) => {
    const [column, fmt] = spec.split("|");
    return parseRef(`${table}/${column}/${row}|${fmt}`);
  });
}

/** RFC 6901 JSON pointer. */
export function getPointer(doc: unknown, pointer: string): unknown {
  if (pointer === "") return doc;
  let node: unknown = doc;
  for (const raw of pointer.slice(1).split("/")) {
    const key = raw.replaceAll("~1", "/").replaceAll("~0", "~");
    if (Array.isArray(node)) {
      if (!/^\d+$/.test(key) || Number(key) >= node.length) {
        throw new Error(`index ${key} out of range at ${pointer}`);
      }
      node = node[Number(key)];
    } else if (node !== null && typeof node === "object" && key in node) {
      node = (node as Record<string, unknown>)[key];
    } else {
      throw new Error(`no ${key} at ${pointer}`);
    }
  }
  return node;
}

function numbers(node: unknown, ref: Ref): number[] {
  if (!Array.isArray(node)) throw new Error(`${serializeRef(ref)} is not an array`);
  return node.filter((v): v is number => typeof v === "number");
}

/** The raw value a reference stands for. `carried` is the element's data-value, if any. */
export function resolveRef(ref: Ref, doc: unknown, carried?: string | null): unknown {
  const node = getPointer(doc, ref.pointer);
  switch (ref.op) {
    case undefined:
      return node;
    case "max":
      return Math.max(...numbers(node, ref));
    case "min":
      return Math.min(...numbers(node, ref));
    case "sum":
      return numbers(node, ref).reduce((total, v) => total + v, 0);
    case "count":
      if (!Array.isArray(node)) throw new Error(`${serializeRef(ref)} is not an array`);
      return ref.arg === undefined
        ? node.length
        : node.filter((item) => String(item) === ref.arg).length;
    case "year": {
      const year = /\((\d{4})\)/.exec(String(node));
      if (!year) throw new Error(`${serializeRef(ref)} has no year in parentheses`);
      return Number(year[1]);
    }
    case "within":
    case "member": {
      const value = Number(carried);
      if (carried === null || carried === undefined || !Number.isFinite(value)) {
        throw new Error(`${serializeRef(ref)} needs a numeric data-value`);
      }
      const values = numbers(node, ref);
      const ok =
        ref.op === "member"
          ? values.includes(value)
          : value >= Math.min(...values) && value <= Math.max(...values);
      if (!ok) throw new Error(`${value} is not ${ref.op} ${serializeRef(ref)}`);
      return value;
    }
  }
  throw new Error(`unknown operation in ${serializeRef(ref)}`);
}

export function renderRef(ref: Ref, doc: unknown, carried?: string | null): string {
  return format(resolveRef(ref, doc, carried), ref.format);
}

/** Number-like tokens of a text, as printed: "−9%", "19.237", "0,75", "1991". */
export function numberTokens(text: string): string[] {
  return text.match(/[−+]?\d+(?:[.,]\d+)*%?/gu) ?? [];
}
