import { buildIndex, normalize, search } from "../src/lib/search";

const index = buildIndex({
  municipality_id: [1, 2, 3, 4, 5, 6],
  municipality_name: ["São Paulo", "Sorriso", "Bom Jesus", "Bom Jesus", "Paulo Afonso", "Assis"],
  state_abbreviation: ["SP", "MT", "PI", "RS", "BA", "SP"],
});

describe("municipality search", () => {
  it("ignores accents, case and punctuation", () => {
    expect(normalize("  São-Paulo ")).toBe("sao paulo");
    expect(search(index, "SAO PAULO", 8).map((entry) => entry.id)).toEqual([1]);
  });

  it("ranks the exact name, then names starting with the query, then words, then the rest", () => {
    expect(search(index, "paulo", 8).map((entry) => entry.id)).toEqual([5, 1]);
    expect(search(index, "s", 8).map((entry) => entry.name)).toEqual([
      "São Paulo",
      "Sorriso",
      "Assis",
      "Bom Jesus",
      "Bom Jesus",
      "Paulo Afonso",
    ]);
  });

  it("keeps homonyms apart by state and respects the limit", () => {
    expect(search(index, "bom jesus", 8).map((entry) => entry.state)).toEqual(["PI", "RS"]);
    expect(search(index, "s", 2)).toHaveLength(2);
    expect(search(index, "   ", 8)).toEqual([]);
  });
});
