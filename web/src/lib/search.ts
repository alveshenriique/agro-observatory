// Municipality search over municipalities.json: accent- and case-insensitive, names that
// start with the query first, then names with a word that starts with it, then the rest.
export interface SearchEntry {
  id: number;
  name: string;
  state: string;
  key: string;
}

export interface MunicipalityIndex {
  municipality_id: number[];
  municipality_name: string[];
  state_abbreviation: string[];
}

export function normalize(text: string): string {
  return text
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

export function buildIndex(table: MunicipalityIndex): SearchEntry[] {
  return table.municipality_id.map((id, i) => {
    const name = table.municipality_name[i] ?? "";
    return { id, name, state: table.state_abbreviation[i] ?? "", key: normalize(name) };
  });
}

const collator = new Intl.Collator("pt-BR");

export function search(index: SearchEntry[], query: string, limit: number): SearchEntry[] {
  const q = normalize(query);
  if (q === "") return [];
  const ranked: [number, SearchEntry][] = [];
  for (const entry of index) {
    let rank: number;
    if (entry.key === q) rank = 0;
    else if (entry.key.startsWith(q)) rank = 1;
    else if (entry.key.includes(` ${q}`)) rank = 2;
    else if (entry.key.includes(q)) rank = 3;
    else continue;
    ranked.push([rank, entry]);
  }
  ranked.sort(
    ([ra, a], [rb, b]) =>
      ra - rb || collator.compare(a.name, b.name) || collator.compare(a.state, b.state),
  );
  return ranked.slice(0, limit).map(([, entry]) => entry);
}
