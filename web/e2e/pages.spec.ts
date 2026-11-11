// Every page must render the shared layout and pass axe (WCAG 2.x A and AA) in both
// themes; the Playwright projects run each test under light and dark colour schemes.
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const pages = [
  { path: "/", heading: "Análise" },
  { path: "/explorar/", heading: "Explorar" },
  { path: "/municipios/", heading: "Municípios" },
  { path: "/metodo/", heading: "Método" },
];

for (const { path, heading } of pages) {
  test(`${path} renders the shared layout`, async ({ page }) => {
    await page.goto(path);
    await expect(page).toHaveTitle(`${heading} · Atlas da Lavoura`);
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
    await expect(page.locator(".top-strip")).toContainText("Dados até a safra");
    const navigation = page.getByRole("navigation", { name: "Páginas do site" });
    await expect(navigation.getByRole("link")).toHaveCount(4);
    await expect(navigation.getByRole("link", { name: heading })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expect(page.locator("footer")).toContainText("projeto independente");
    await expect(page.locator("footer")).toContainText("Fonte: IBGE");
  });

  test(`${path} has no axe violations (WCAG 2.x A/AA)`, async ({ page }) => {
    await page.goto(path);
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(results.violations).toEqual([]);
  });
}
