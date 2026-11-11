// Short and full source citations, read from catalog.sources. The footer and the figures use
// the short form ("BR-DWGD (Xavier et al., 2022)") and link to the full citations on the
// Método page; the year comes from the citation text itself.
import type { CatalogJson } from "../types/data/catalog";
import { loadCatalog } from "./data";
import { type Sourced, sourced } from "./sourced";

export interface ShortCitation {
  author: string;
  year: Sourced;
}

export function brdwgdShortCitation(): ShortCitation {
  const source = loadCatalog().sources.brdwgd;
  if (!source) throw new Error("catalog.json has no brdwgd source");
  const author = source.publisher.split(",")[0]?.trim() ?? "";
  return { author, year: sourced("catalog.json", "/sources/brdwgd/attribution_pt", "year", "year") };
}

export interface FullCitation {
  key: string;
  name: string;
  citation: string;
  publisher: string;
  period: string | null;
  usedFor: string;
  terms: string;
  url: string;
  src: (field: string) => string;
}

/** Every source in catalog order, in one uniform shape for the Método page. */
export function fullCitations(): FullCitation[] {
  const catalog: CatalogJson = loadCatalog();
  return Object.entries(catalog.sources).map(([key, source]) => ({
    key,
    name: source.name_pt,
    citation: source.attribution_pt.replace(/^Fonte:\s*/u, ""),
    publisher: source.publisher,
    period: source.reference_period_pt,
    usedFor: source.used_for_pt,
    terms: source.terms_pt,
    url: source.url,
    src: (field: string) => `catalog.json#/sources/${key}/${field}|text`,
  }));
}
