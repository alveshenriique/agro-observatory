// Structural numbers: the numbering of figures, tables and notes, and the markers of
// numbered lists. They are editorial, not data, so they carry no reference to the data
// package; instead they are marked explicitly (data-structural) and must follow rules strict
// enough that a data number cannot pass as one:
// - a figure, table or note mark is a text-only element that reads exactly "Figura N",
//   "Tabela N" or "Nota N", where N is its position among the marks of the same kind, in
//   document order, and it cites no data;
// - a numbered list is an <ol data-structural="list"> that counts from 1: no start, no
//   reversed, no value on its items.
// Everything inside a mark other than the mark's own number is still checked as data, and a
// number in CSS-generated content (::before, ::after) is always refused.
// Shared by the build and the provenance test (e2e/provenance.ts); no DOM here.
export const STRUCTURAL_LABELS = { figure: "Figura", table: "Tabela", note: "Nota" } as const;

export type StructuralKind = keyof typeof STRUCTURAL_LABELS;

export function structuralText(kind: StructuralKind, n: number): string {
  return `${STRUCTURAL_LABELS[kind]} ${n}`;
}

export interface StructuralMark {
  kind: string;
  text: string;
  where: string;
  hasChildren: boolean;
  citesData: boolean;
}

/** One verdict per mark (true when valid), plus the problems found. */
export function checkStructuralMarks(marks: StructuralMark[]): {
  valid: boolean[];
  problems: string[];
} {
  const seen = new Map<string, number>();
  const problems: string[] = [];
  const valid = marks.map((mark) => {
    if (!(mark.kind in STRUCTURAL_LABELS)) {
      problems.push(`${mark.where}: unknown structural kind "${mark.kind}"`);
      return false;
    }
    const kind = mark.kind as StructuralKind;
    const n = (seen.get(kind) ?? 0) + 1;
    seen.set(kind, n);
    const expected = structuralText(kind, n);
    if (mark.hasChildren || mark.citesData || mark.text.trim() !== expected) {
      problems.push(`${mark.where}: structural mark "${mark.text.trim()}" must read "${expected}"`);
      return false;
    }
    return true;
  });
  return { valid, problems };
}

export interface NumberedList {
  where: string;
  tag: string;
  structural: boolean;
  start: number | null;
  reversed: boolean;
  hasValues: boolean;
}

export function checkNumberedLists(lists: NumberedList[]): string[] {
  return lists.flatMap((list) => {
    if (!list.structural) return [`${list.where}: numbered list not marked as structural`];
    if (list.tag !== "ol" || list.start !== 1 || list.reversed || list.hasValues) {
      return [`${list.where}: a structural list must be an <ol> counting from 1`];
    }
    return [];
  });
}
