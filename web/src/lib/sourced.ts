// Build-time helpers that turn a reference into the value, the printed text and the
// data-src attribute, so the page and its provenance can never disagree (see provenance.ts).
import { loadDataFile } from "./data";
import type { FormatName } from "./format";
import { type Op, type Ref, renderRef, resolveRef, serializeRef } from "./provenance";

export interface Sourced {
  value: unknown;
  text: string;
  src: string;
}

export function sourced(
  file: string,
  pointer: string,
  format: FormatName,
  op?: Op,
  arg?: string,
): Sourced {
  const ref: Ref = { file, pointer, format };
  if (op !== undefined) ref.op = op;
  if (arg !== undefined) ref.arg = arg;
  const doc = loadDataFile<unknown>(file);
  return { value: resolveRef(ref, doc), text: renderRef(ref, doc), src: serializeRef(ref) };
}

/** An axis tick: the value is checked to lie within (or be one of) the plotted column. */
export function tick(
  file: string,
  pointer: string,
  format: FormatName,
  op: "within" | "member",
  value: number,
): Sourced & { carried: string } {
  const ref: Ref = { file, pointer, op, format };
  const carried = String(value);
  const doc = loadDataFile<unknown>(file);
  return {
    value: resolveRef(ref, doc, carried),
    text: renderRef(ref, doc, carried),
    src: serializeRef(ref),
    carried,
  };
}

/** Index of the first row of a columnar table matching every key (throws if none). */
export function rowIndex(
  table: Record<string, readonly unknown[]>,
  keys: Record<string, unknown>,
): number {
  const columns = Object.entries(keys);
  const length = Object.values(table)[0]?.length ?? 0;
  for (let row = 0; row < length; row++) {
    if (columns.every(([column, value]) => table[column]?.[row] === value)) return row;
  }
  throw new Error(`no row with ${JSON.stringify(keys)}`);
}
