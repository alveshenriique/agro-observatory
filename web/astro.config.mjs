// @ts-check
import react from "@astrojs/react";
import { defineConfig } from "astro/config";

// Static site served by a CDN; every page prerenders at build time and React runs only
// inside islands. The data files come from public/data/, filled by `npm run setup`.
export default defineConfig({
  site: "https://atlasdalavoura.com.br",
  integrations: [react()],
});
