// Every page must render the shared layout and pass axe (WCAG 2.x A and AA) in both
// themes; the Playwright projects run each test under light and dark colour schemes.
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const pages = [
  { path: "/", heading: "Quando falta chuva na floração, a soja rende menos", nav: "Análise", title: "Análise" },
  { path: "/explorar/", heading: "Explorar", nav: "Explorar", title: "Explorar" },
  { path: "/municipios/", heading: "Municípios", nav: "Municípios", title: "Municípios" },
  { path: "/metodo/", heading: "Método", nav: "Método", title: "Método" },
  { path: "/municipio/5107925/", heading: "Sorriso", nav: "Municípios", title: "Sorriso (MT)" },
];

for (const { path, heading, nav, title } of pages) {
  test(`${path} renders the shared layout`, async ({ page }) => {
    await page.goto(path);
    await expect(page).toHaveTitle(`${title} · Atlas da Lavoura`);
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
    await expect(page.locator(".top-strip")).toContainText("Dados até a safra");
    const navigation = page.getByRole("navigation", { name: "Páginas do site" });
    await expect(navigation.getByRole("link")).toHaveCount(4);
    await expect(navigation.getByRole("link", { name: nav })).toHaveAttribute(
      "aria-current",
      "page",
    );
    const footer = page.locator("footer");
    await expect(footer).toContainText("não causalidade");
    await expect(footer).toContainText(
      "Fontes: IBGE, Banco Central, BR-DWGD (Xavier et al., 2022) e Conab.",
    );
    await expect(footer.getByRole("link", { name: /Citações completas/ })).toHaveAttribute(
      "href",
      "/metodo/#fontes",
    );
    await expect(footer).toContainText("projeto independente");
    await expect(footer).toContainText("Versão dos dados");
  });

  test(`${path} has no axe violations (WCAG 2.x A/AA)`, async ({ page }) => {
    await page.goto(path);
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(results.violations).toEqual([]);
  });
}

test("the Método page lists every source of the catalog in one format", async ({
  page,
  request,
}) => {
  await page.goto("/metodo/");
  const base = await page.evaluate(() => document.documentElement.dataset.dataBase ?? "");
  const catalog = (await (await request.get(`${base}catalog.json`)).json()) as {
    sources: Record<string, { name_pt: string }>;
  };
  const sources = page.locator("#fontes .source");
  await expect(sources).toHaveCount(Object.keys(catalog.sources).length);
  const shapes = await sources.evaluateAll((items) =>
    items.map((item) =>
      [...item.querySelectorAll("dt")].map((dt) => dt.textContent?.trim()).join("|"),
    ),
  );
  expect(new Set(shapes).size).toBe(1);
  for (const source of Object.values(catalog.sources)) {
    await expect(sources.getByRole("heading", { level: 3, name: source.name_pt })).toBeVisible();
  }
});
