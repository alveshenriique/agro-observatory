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

const cache = new Map<string, unknown>();

/** A file of the pinned data package, parsed once per build. */
export function loadDataFile<T>(name: string): T {
  if (!cache.has(name)) {
    const file = path.join(webRoot, "public", "data", release.data_version, name);
    cache.set(name, JSON.parse(readFileSync(file, "utf-8")));
  }
  return cache.get(name) as T;
}

export function loadCatalog(): CatalogJson {
  return loadDataFile<CatalogJson>("catalog.json");
}
