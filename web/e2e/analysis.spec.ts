// The Análise page. Every test runs under the light and the dark colour scheme (the
// Playwright projects). The provenance tests are the page's main rule: no number typed by
// hand, every one read from the data package.
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import { tokens } from "../src/lib/tokens";
import { findUnsourcedNumbers } from "./provenance";

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];
const PANELS_IN_VIEW = ".figure__panels > .panels > .panel";

/** Titles with a line ending in a word of one or two letters, as laid out right now. */
async function shortWordLineEndings(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const found = new Set<string>();
    for (const heading of document.querySelectorAll("h1, h2, h3, h4")) {
      const words: { text: string; top: number }[] = [];
      const walker = document.createTreeWalker(heading, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        const text = node.textContent ?? "";
        // Only ordinary spaces separate words here: a no-break space keeps them together.
        const pattern = /[^ \n\t]+/g;
        for (let m = pattern.exec(text); m; m = pattern.exec(text)) {
          const range = document.createRange();
          range.setStart(node, m.index);
          range.setEnd(node, m.index + m[0].length);
          const rects = range.getClientRects();
          const last = rects[rects.length - 1];
          if (last && last.width > 0) words.push({ text: m[0], top: Math.round(last.top) });
        }
      }
      words.forEach((word, i) => {
        const next = words[i + 1];
        const tail = word.text.split(" ").pop()?.replace(/[^\p{L}]/gu, "") ?? "";
        if (next && next.top > word.top && tail.length > 0 && tail.length <= 2) {
          found.add(heading.textContent ?? "");
        }
      });
    }
    return [...found];
  });
}

async function scrollThrough(page: Page) {
  await page.evaluate(async () => {
    for (let y = 0; y < document.body.scrollHeight; y += 400) {
      window.scrollTo(0, y);
      await new Promise((resolve) => setTimeout(resolve, 30));
    }
  });
}

test.describe("numbers come from the data package", () => {
  for (const path of ["/", "/metodo/", "/explorar/", "/municipios/", "/municipio/5107925/"]) {
    test(`${path} has no number typed by hand`, async ({ page, request }) => {
      await page.goto(path);
      expect(await findUnsourcedNumbers(page, request)).toEqual([]);
    });
  }

  test("the open tooltip and the data tables are covered too", async ({ page, request }) => {
    await page.goto("/");
    await page.locator(".figure__data summary").click();
    await page.locator(".panels-more summary").click();
    await page.locator(".stat__note summary").click();
    await page.locator(".figure__focus .bar").first().focus();
    await expect(page.locator(".figure__focus .chart-tooltip")).toBeVisible();
    expect(await findUnsourcedNumbers(page, request)).toEqual([]);
  });

  test("a number typed by hand fails the check", async ({ page, request }) => {
    await page.goto("/");
    await page.evaluate(() => {
      const p = document.createElement("p");
      p.textContent = "Em 2019, 12% das safras ficaram abaixo da tendência.";
      document.querySelector("main")?.append(p);
    });
    const issues = await findUnsourcedNumbers(page, request);
    expect(issues.map((issue) => issue.problem)).toEqual([
      "number without provenance",
    ]);
    expect(issues[0]?.text).toContain("2019");
  });

  test("figure and table numbering stay, as structural numbers", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('figure [data-structural="figure"]')).toHaveText(["Figura 1"]);
    await expect(page.locator('figure [data-structural="table"]')).toHaveText([
      "Tabela 1",
      "Tabela 2",
    ]);
    await page.goto("/metodo/");
    const sources = page.locator('ol.sources[data-structural="list"] > li');
    expect(await sources.count()).toBeGreaterThan(1);
    expect(await sources.first().evaluate((li) => getComputedStyle(li).listStyleType)).toBe(
      "decimal",
    );
  });

  test("a data number cannot pass as a structural one", async ({ page, request }) => {
    await page.goto("/");
    await page.evaluate(() => {
      document.querySelector("main")?.insertAdjacentHTML(
        "beforeend",
        [
          // out of sequence: the next figure on this page would be Figura 2
          '<p><span data-structural="figure">Figura 88</span></p>',
          // a percentage is no note number
          '<p><span data-structural="note">73%</span> das safras</p>',
          // a whole sentence of data under a table mark
          '<p data-structural="table">Em 2005, 66% abaixo da tendência</p>',
          // a structural list that does not count from 1
          '<ol data-structural="list" start="537"><li>item</li></ol>',
          // a numbered list without the structural mark
          "<ol><li>item</li></ol>",
          // a number in CSS-generated content
          '<style>.disguise::before { content: "−9%"; }</style><p class="disguise"></p>',
        ].join(""),
      );
    });
    const problems = (await findUnsourcedNumbers(page, request)).map((issue) => issue.problem);
    expect(problems).toEqual(
      expect.arrayContaining([
        expect.stringContaining('"Figura 88" must read "Figura 2"'),
        expect.stringContaining('"73%" must read "Nota 1"'),
        expect.stringContaining('must read "Tabela 3"'),
        expect.stringContaining("a structural list must be an <ol> counting from 1"),
        expect.stringContaining("numbered list not marked as structural"),
        "number in CSS-generated content",
      ]),
    );
    // The numbers inside the refused marks are then checked as data, and have no provenance.
    expect(problems.filter((problem) => problem === "number without provenance")).toHaveLength(3);
  });

  test("a number that disagrees with its file fails the check", async ({ page, request }) => {
    await page.goto("/");
    await page.evaluate(() => {
      const main = document.querySelector(".finding .finding__compare");
      if (main) main.textContent = "44%";
      const bar = document.querySelector(".figure__focus .bar");
      bar?.setAttribute("aria-label", "2005: −70% em relação à tendência");
    });
    const problems = (await findUnsourcedNumbers(page, request)).map((issue) => issue.problem);
    expect(problems.some((problem) => problem.startsWith("44% is not what"))).toBe(true);
    expect(problems.some((problem) => problem.startsWith("−70% is not what"))).toBe(true);
  });
});

test.describe("typography and layout", () => {
  test("three voices of IBM Plex: serif titles, sans text, mono numbers", async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => document.fonts.ready);
    const fontOf = (selector: string) =>
      page
        .locator(selector)
        .first()
        .evaluate((el) => {
          const style = getComputedStyle(el);
          return { family: style.fontFamily, features: style.fontFeatureSettings };
        });
    const weightOf = (selector: string) =>
      page
        .locator(selector)
        .first()
        .evaluate((el) => getComputedStyle(el).fontWeight);
    expect((await fontOf("h1")).family).toMatch(/^"IBM Plex Serif"/);
    expect(await weightOf("h1")).toBe("400");
    expect((await fontOf(".opening__deck")).family).toMatch(/^"IBM Plex Serif"/);
    expect((await fontOf(".stat__text")).family).toMatch(/^"IBM Plex Sans"/);
    // The main number is the one number in the sans bold; every other stays in the mono.
    expect((await fontOf(".finding__number")).family).toMatch(/^"IBM Plex Sans"/);
    expect(await weightOf(".finding__number")).toBe(String(tokens.displayNumber.weight));
    const stat = await fontOf(".stat__number");
    expect(stat.family).toMatch(/^"IBM Plex Mono"/);
    expect(stat.features).toContain("ss04");
    expect((await fontOf(".kicker")).family).toMatch(/^"IBM Plex Mono"/);
    const loaded = await page.evaluate(() =>
      [
        '400 16px "IBM Plex Sans"',
        '700 16px "IBM Plex Sans"',
        '400 16px "IBM Plex Serif"',
        '400 16px "IBM Plex Mono"',
        '600 16px "IBM Plex Mono"',
      ].map((font) => document.fonts.check(font)),
    );
    expect(loaded).toEqual([true, true, true, true, true]);
  });

  test("the page sits on the warm white, the search on its own band", async ({ page }, testInfo) => {
    await page.goto("/");
    const theme = testInfo.project.name === "dark" ? "dark" : "light";
    const rgb = (hex: string) =>
      `rgb(${[1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)).join(", ")})`;
    const background = (selector: string) =>
      page.locator(selector).evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(await background("body")).toBe(rgb(tokens.themes[theme].background));
    expect(await background(".search-band")).toBe(rgb(tokens.themes[theme].band));
    const band = await page.locator(".search-band").boundingBox();
    expect(band?.x).toBe(0);
    expect(band?.width).toBe(page.viewportSize()?.width);
  });

  test("every character on the page is in the self-hosted Latin1 subsets", async ({ page }) => {
    await page.goto("/");
    const ranges = tokens.typefaces.numbers.unicodeRange.split(",").map((part) => {
      const [start, end] = part.trim().replace("U+", "").split("-");
      return [parseInt(start ?? "0", 16), parseInt(end ?? start ?? "0", 16)] as const;
    });
    const text = await page.evaluate(() => document.body.innerText);
    const outside = [...new Set(text.replace(/\s/g, ""))].filter((char) => {
      const code = char.codePointAt(0) ?? 0;
      return !ranges.some(([start, end]) => code >= start && code <= end);
    });
    expect(outside).toEqual([]);
  });

  test("a 1,240 px grid with a reading measure for the text", async ({ page }) => {
    await page.setViewportSize({ width: 1600, height: 900 });
    await page.goto("/");
    const width = (selector: string) =>
      page
        .locator(selector)
        .first()
        .evaluate((el) => el.getBoundingClientRect().width);
    expect(await width(".site-header .container")).toBeLessThanOrEqual(1240);
    expect(await width(".top-strip .container")).toBe(await width(".site-header .container"));
    expect(await width(".opening__deck")).toBeLessThanOrEqual(38 * 16);
    expect(await width(".figure")).toBeGreaterThan(1100);
  });

  test("no horizontal scroll on a phone", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 780 });
    await page.goto("/");
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
});

test.describe("the opening and the figure", () => {
  test("the main number is large and in the dry colour", async ({ page }, testInfo) => {
    await page.goto("/");
    const theme = testInfo.project.name === "dark" ? "dark" : "light";
    const style = await page
      .locator(".finding__main .finding__number")
      .evaluate((el) => ({ color: getComputedStyle(el).color, size: getComputedStyle(el).fontSize }));
    const hex = tokens.themes[theme].dry;
    const rgb = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)).join(", ");
    expect(style.color).toBe(`rgb(${rgb})`);
    expect(parseFloat(style.size)).toBeGreaterThanOrEqual(56);
    await expect(page.locator("h1")).toHaveText("Quando falta chuva na floração, a soja rende menos");
  });

  test("the figure has the focus state, every state, legend, source and links", async ({
    page,
    request,
  }) => {
    await page.goto("/");
    const figure = page.locator("figure.figure");
    const focusBars = figure.locator(".figure__focus .bar");
    const focusRows = figure.locator("details table").nth(1).locator("tbody tr");
    await expect(focusBars).toHaveCount(await focusRows.count());
    await expect(figure.locator(".panel")).toHaveCount(
      await figure.locator("details table").first().locator("tbody tr").count(),
    );
    await expect(figure.locator(".legend li").first()).toContainText("seca na floração");
    await expect(figure.locator(".figure__title")).toContainText(
      "Figura 1. Rendimento da soja no Rio Grande do Sul em relação à tendência",
    );
    await expect(figure.locator(".figure__reading").first()).toContainText(
      "Abaixo de zero, a safra rendeu menos que a tendência.",
    );
    const caption = figure.locator("figcaption");
    await expect(caption).toContainText("Fonte: IBGE");
    await expect(caption.getByRole("link", { name: "Fonte" })).toHaveAttribute(
      "href",
      "/metodo/#fontes",
    );
    const data = caption.getByRole("link", { name: "Dados", exact: true });
    const response = await request.get((await data.getAttribute("href")) ?? "");
    expect(response.ok()).toBe(true);
    await expect(caption.getByRole("link", { name: "Método", exact: true })).toHaveAttribute(
      "href",
      "/metodo/",
    );
    await expect(caption.getByRole("link", { name: "Link", exact: true })).toHaveAttribute(
      "href",
      "#figura-1",
    );
    await expect(figure).toHaveAttribute("id", "figura-1");
  });

  test("the worst years of the focus state are labelled", async ({ page }) => {
    await page.goto("/");
    const anomalies = await page
      .locator(".figure__focus .bar")
      .evaluateAll((bars) =>
        bars.map((bar) => {
          const label = bar.getAttribute("aria-label") ?? "";
          const [year, value] = label.split(": ");
          return { year, value: Number((value ?? "").split("%")[0]?.replace("−", "-")) };
        }),
      );
    const worst = [...anomalies]
      .sort((a, b) => a.value - b.value)
      .slice(0, 3)
      .map((bar) => bar.year);
    const notes = await page.locator(".figure__focus .note").allTextContents();
    expect(notes.map((note) => note.split(" ")[0]).sort()).toEqual([...worst].sort());
  });

  test("bars and tooltip work from the keyboard", async ({ page }) => {
    await page.goto("/");
    const bars = page.locator(".figure__focus .bar");
    const tooltip = page.locator(".figure__focus .chart-tooltip");
    await expect(page.locator(".figure__focus .bar[tabindex='0']")).toHaveCount(1);
    await bars.first().focus();
    await expect(tooltip).toBeVisible();
    await expect(tooltip).toHaveText((await bars.first().getAttribute("aria-label")) ?? "");
    await page.keyboard.press("ArrowRight");
    await expect(bars.nth(1)).toBeFocused();
    await expect(tooltip).toHaveText((await bars.nth(1).getAttribute("aria-label")) ?? "");
    await page.keyboard.press("End");
    await expect(bars.last()).toBeFocused();
    await expect(page.locator(".figure__focus .bar[tabindex='0']")).toHaveCount(1);
    await page.keyboard.press("Escape");
    await expect(tooltip).toBeHidden();
  });

  test("bars grow when they enter the screen", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/");
    const lastPanelBar = page.locator(PANELS_IN_VIEW).last().locator(".bar").first();
    const transform = () => lastPanelBar.evaluate((el) => getComputedStyle(el).transform);
    expect(await transform()).toBe("matrix(1, 0, 0, 0, 0, 0)");
    await scrollThrough(page);
    await expect.poll(transform, { timeout: 5000 }).toBe("none");
  });
});

test.describe("with reduced motion", () => {
  test.use({ reducedMotion: "reduce" });

  test("bars are drawn complete, without waiting to scroll", async ({ page }) => {
    await page.goto("/");
    const transform = await page
      .locator(PANELS_IN_VIEW)
      .last()
      .locator(".bar")
      .first()
      .evaluate((el) => getComputedStyle(el).transform);
    expect(transform).toBe("none");
  });
});

test.describe("editorial review", () => {
  test("every block starts on the same grid line as the brand", async ({ page }) => {
    for (const width of [1600, 1024, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/");
      const lefts = await page.evaluate(() =>
        [".site-header .brand", ".opening__title", ".figure", ".support", "#busca-titulo"].map(
          (selector) => Math.round(document.querySelector(selector)?.getBoundingClientRect().left ?? -1),
        ),
      );
      expect(new Set(lefts).size, `left edges at ${width}px: ${lefts.join(", ")}`).toBe(1);
      const deck = await page.locator(".opening__deck").evaluate((el) => el.getBoundingClientRect().width);
      expect(deck).toBeLessThanOrEqual(38 * 16);
    }
  });

  test("the main number sits beside the title on a computer, after the deck on a phone", async ({
    page,
  }) => {
    const boxes = async () => {
      await page.goto("/");
      await page.evaluate(() => document.fonts.ready);
      return page.evaluate(() =>
        Object.fromEntries(
          [".site-header .brand", ".opening__title", ".opening__deck", ".finding"].map((s) => {
            const r = document.querySelector(s)?.getBoundingClientRect();
            return [s, { left: r?.left ?? 0, right: r?.right ?? 0, top: r?.top ?? 0, bottom: r?.bottom ?? 0 }];
          }),
        ),
      );
    };
    for (const width of [1440, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      const b = await boxes();
      expect(b[".finding"]!.left, `at ${width}px`).toBeGreaterThan(b[".opening__title"]!.right);
      expect(Math.abs(b[".finding"]!.top - b[".opening__title"]!.top), `at ${width}px`).toBeLessThan(40);
      expect(b[".finding"]!.bottom, "in the first screen").toBeLessThan(900);
      expect(b[".opening__deck"]!.top - b[".opening__title"]!.bottom).toBeLessThan(40);
    }
    await page.setViewportSize({ width: 390, height: 844 });
    const phone = await boxes();
    expect(phone[".finding"]!.top).toBeGreaterThan(phone[".opening__deck"]!.bottom);
    expect(Math.round(phone[".finding"]!.left)).toBe(Math.round(phone[".site-header .brand"]!.left));
  });

  test("the mono is only for numbers and short labels", async ({ page }) => {
    await page.goto("/");
    const family = (selector: string) =>
      page
        .locator(selector)
        .first()
        .evaluate((el) => getComputedStyle(el).fontFamily);
    for (const selector of [
      ".finding__text",
      ".legend li",
      ".figure__title",
      ".figure__reading",
      ".panel__stat",
      ".figure__caption p",
      ".figure__links a",
      ".figure__data summary",
      ".panels-more > summary",
      ".stat__text",
      ".stat__note > summary",
      ".search-band__intro p",
      ".search__help",
    ]) {
      expect(await family(selector), selector).toMatch(/^"IBM Plex Sans"/);
    }
    for (const selector of [
      ".kicker",
      ".top-strip",
      ".finding__text .num",
      ".figure__title .num",
      ".figure__reading .num",
      ".panel__stat .num",
      ".figure__caption .num",
      ".anomaly-chart__y span",
      ".note",
      ".stat__number",
      ".search__label",
    ]) {
      expect(await family(selector), selector).toMatch(/^"IBM Plex Mono"/);
    }
    await page.locator(".figure__focus .bar").first().focus();
    expect(await family(".figure__focus .chart-tooltip")).toMatch(/^"IBM Plex Sans"/);
    expect(await family(".figure__focus .chart-tooltip .num")).toMatch(/^"IBM Plex Mono"/);
  });

  test("no title line ends with a word of one or two letters", async ({ page }) => {
    for (const width of [360, 768, 1280, 1600]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/");
      expect(await shortWordLineEndings(page), `at ${width}px`).toEqual([]);
    }
  });

  test("the title check catches a short word left at the end of a line", async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => {
      const title = document.createElement("h2");
      title.style.width = "4ch";
      title.textContent = "Chuva a mais";
      document.querySelector("main")?.append(title);
    });
    expect(await shortWordLineEndings(page)).toEqual(["Chuva a mais"]);
  });

  test("six states in view, the rest behind a keyboard-friendly button", async ({ page }) => {
    await page.goto("/");
    const states = await page.locator("details.figure__data table").first().locator("tbody tr").count();
    await expect(page.locator(PANELS_IN_VIEW)).toHaveCount(6);
    const more = page.locator("details.panels-more");
    const button = more.locator("summary");
    await expect(button).toHaveAccessibleName(`Mostrar as ${states} UFs`);
    await expect(button.locator(".when-closed")).toBeVisible();
    await expect(button.locator(".when-open")).toBeHidden();
    await expect(more).not.toHaveAttribute("open", "");
    await expect(more.locator(".panel").first()).toBeHidden();
    await button.focus();
    await page.keyboard.press("Enter");
    await expect(more).toHaveAttribute("open", "");
    await expect(page.locator(".panel:visible")).toHaveCount(states);
    await expect(button).toHaveAccessibleName("Mostrar menos UFs");
    await page.keyboard.press("Enter");
    await expect(more.locator(".panel").first()).toBeHidden();
  });

  test("the comparison-cell definition opens on demand", async ({ page }) => {
    await page.goto("/");
    const note = page.locator("details.stat__note");
    await expect(note.locator("summary")).toHaveText("O que é uma célula comparada?");
    await expect(note.locator("p")).toBeHidden();
    await note.locator("summary").click();
    await expect(note.locator("p")).toBeVisible();
    await expect(note.locator("p")).toContainText("Célula comparada:");
  });
});

test.describe("without JavaScript", () => {
  test.use({ javaScriptEnabled: false });

  test("the states and the definition still open, and the bars are drawn", async ({ page }) => {
    await page.goto("/");
    const more = page.locator("details.panels-more");
    await more.locator("summary").click();
    await expect(more.locator(".panel").first()).toBeVisible();
    const transform = await more
      .locator(".bar")
      .first()
      .evaluate((el) => getComputedStyle(el).transform);
    expect(transform).toBe("none");
    await page.locator("details.stat__note summary").click();
    await expect(page.locator("details.stat__note p")).toBeVisible();
  });
});

test.describe("municipality search", () => {
  test("autocomplete leads to the municipality page", async ({ page }) => {
    await page.goto("/");
    const input = page.getByRole("combobox", { name: "Município" });
    await input.fill("sorriso");
    const option = page.getByRole("option").first();
    await expect(option).toContainText("Sorriso");
    await expect(option).toContainText("MT");
    await expect(input).toHaveAttribute("aria-expanded", "true");
    await input.press("ArrowDown");
    await expect(option).toHaveAttribute("aria-selected", "true");
    await expect(input).toHaveAttribute("aria-activedescendant", (await option.getAttribute("id")) ?? "");
    await input.press("Enter");
    await expect(page).toHaveURL(/\/municipio\/5107925\/$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Sorriso");
    await expect(
      page.getByRole("navigation", { name: "Páginas do site" }).getByRole("link", {
        name: "Municípios",
      }),
    ).toHaveAttribute("aria-current", "page");
  });

  test("the hint is never cut: short on a phone, the full one on a computer", async ({ page }) => {
    const hint = async () => {
      const input = page.getByRole("combobox", { name: "Município" });
      await page.evaluate(() => document.fonts.ready);
      return input.evaluate((el: HTMLInputElement) => {
        const style = getComputedStyle(el);
        const context = document.createElement("canvas").getContext("2d");
        if (!context) return { text: el.placeholder, fits: false };
        context.font = `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
        const room = el.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
        return { text: el.placeholder, fits: context.measureText(el.placeholder).width <= room };
      });
    };
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    expect(await hint()).toEqual({ text: "Ex.: Sorriso", fits: true });
    await page.setViewportSize({ width: 1440, height: 900 });
    await expect.poll(async () => (await hint()).text).toBe("Sorriso, Rio Verde, Patrocínio…");
    expect((await hint()).fits).toBe(true);
  });

  test("Abrir ficha opens the best match for the text", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("combobox", { name: "Município" }).fill("sorriso");
    await page.getByRole("button", { name: "Abrir ficha" }).click();
    await expect(page).toHaveURL(/\/municipio\/5107925\/$/);
  });

  test("accents and case do not matter", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("combobox", { name: "Município" }).fill("SAO PAULO");
    await expect(page.getByRole("option").first()).toContainText("São Paulo");
  });

  test("the open suggestion list has no axe violations", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("combobox", { name: "Município" }).fill("santa");
    await expect(page.getByRole("option").first()).toBeVisible();
    const results = await new AxeBuilder({ page }).withTags(WCAG).analyze();
    expect(results.violations).toEqual([]);
  });
});

test("the page has no axe violations with every chart visible", async ({ page }) => {
  await page.goto("/");
  await page.locator(".panels-more summary").click();
  await page.locator(".stat__note summary").click();
  await scrollThrough(page);
  await page.locator(".figure__data summary").click();
  const results = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  expect(results.violations).toEqual([]);
});
