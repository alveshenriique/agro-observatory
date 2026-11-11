// Build-time access to the data package. The pointer (../data-release.json, at the
// repository root) pins the version; the files live in public/data/<data_version>/,
// extracted by scripts/fetch-data.mjs. This module runs only inside Astro frontmatter
// (Node at build time), never in the browser.
import { readFileSync } from "node:fs";
import path from "node:path";

import type { CatalogJson } from "../types/data/catalog";

// Astro runs (dev, build, preview) with the web/ folder as the working directory; the
// prerender bundle relocates modules, so import.meta.url is not a stable anchor here.
const webRoot = process.cwd();

export interface DataRelease {
  data_version: string;
  release_tag: string;
  asset_url: string;
  sha256: string;
  bytes: number;
  schema_versions: string[];
}

export const release: DataRelease = JSON.parse(
  readFileSync(path.join(webRoot, "..", "data-release.json"), "utf-8"),
) as DataRelease;

/** Base URL path (as served) of the pinned data version. */
export const dataBasePath = `/data/${release.data_version}`;

export function loadCatalog(): CatalogJson {
  const file = path.join(webRoot, "public", "data", release.data_version, "catalog.json");
  return JSON.parse(readFileSync(file, "utf-8")) as CatalogJson;
}

/** "2026.11.10" -> "10/11/2026" (the data version is the generation date). */
export function formatDataVersion(version: string): string {
  const [year, month, day] = version.split(".");
  return `${day}/${month}/${year}`;
}

/** The latest harvest year published in any series ("até a safra 2025"). */
export function latestHarvestYear(catalog: CatalogJson): number {
  return Math.max(...catalog.series.last_year);
}
