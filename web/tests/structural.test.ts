import {
  checkNumberedLists,
  checkStructuralMarks,
  type NumberedList,
  type StructuralMark,
  structuralText,
} from "../src/lib/structural";

const mark = (kind: string, text: string, extra: Partial<StructuralMark> = {}): StructuralMark => ({
  kind,
  text,
  where: `${kind}:${text}`,
  hasChildren: false,
  citesData: false,
  ...extra,
});

const list = (extra: Partial<NumberedList> = {}): NumberedList => ({
  where: "ol.sources",
  tag: "ol",
  structural: true,
  start: 1,
  reversed: false,
  hasValues: false,
  ...extra,
});

describe("structural marks", () => {
  it("accept figures, tables and notes numbered in document order, per kind", () => {
    expect(structuralText("figure", 1)).toBe("Figura 1");
    const result = checkStructuralMarks([
      mark("figure", "Figura 1"),
      mark("table", "Tabela 1"),
      mark("table", " Tabela 2 "),
      mark("figure", "Figura 2"),
      mark("note", "Nota 1"),
    ]);
    expect(result.problems).toEqual([]);
    expect(result.valid).toEqual([true, true, true, true, true]);
  });

  it("refuse a data number dressed as a structural one", () => {
    const result = checkStructuralMarks([
      mark("figure", "Figura 1"),
      mark("figure", "Figura 88"),
      mark("note", "73%"),
      mark("table", "Tabela 1 de 537"),
      mark("figure", "Figura 3", { hasChildren: true }),
      mark("table", "Tabela 2", { citesData: true }),
      mark("count", "Contagem 1"),
    ]);
    expect(result.valid).toEqual([true, false, false, false, false, false, false]);
    expect(result.problems).toHaveLength(6);
    expect(result.problems[0]).toContain('must read "Figura 2"');
  });

  it("accept only <ol> lists counting from 1, always marked", () => {
    expect(checkNumberedLists([list()])).toEqual([]);
    expect(checkNumberedLists([list({ structural: false })])).toEqual([
      "ol.sources: numbered list not marked as structural",
    ]);
    for (const wrong of [{ start: 88 }, { reversed: true }, { hasValues: true }, { tag: "ul" }]) {
      expect(checkNumberedLists([list(wrong)])).toHaveLength(1);
    }
  });
});
