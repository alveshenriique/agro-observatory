// Checks that every data number on a page comes from the data package. It walks the visible
// text and the attributes read by assistive technology, finds each number and requires the
// nearest provenance in the markup (data-src, or data-row with data-src-table/cols, see
// src/lib/provenance.ts). Then it fetches the referenced files from the server, as the
// browser does, and requires that the page prints exactly what they say.
// Structural numbers (figure, table and note numbering, numbered lists) are the only
// exception, and only when they follow the rules of src/lib/structural.ts; a number in
// CSS-generated content is always refused.
import type { APIRequestContext, Page } from "@playwright/test";

import {
  numberTokens,
  parseRefs,
  type Ref,
  renderRef,
  rowRefs,
  serializeRef,
} from "../src/lib/provenance";
import {
  checkNumberedLists,
  checkStructuralMarks,
  type NumberedList,
  type StructuralMark,
} from "../src/lib/structural";

export interface NumberIssue {
  text: string;
  where: string;
  problem: string;
}

interface Item {
  text: string;
  where: string;
  src: string | null;
  carried: string | null;
  table: string | null;
  cols: string | null;
  row: string | null;
  mark: number | null; // index of the structural mark holding this text, if any
}

interface Collected {
  base: string;
  items: Item[];
  marks: StructuralMark[];
  lists: NumberedList[];
  generated: { text: string; where: string }[];
}

const ATTRIBUTES = [
  "aria-label",
  "aria-description",
  "aria-valuetext",
  "aria-roledescription",
  "title",
  "alt",
  "placeholder",
];

async function collect(page: Page): Promise<Collected> {
  return page.evaluate((attributes) => {
    const describe = (el: Element) => {
      const classes = el.getAttribute("class")?.trim().split(/\s+/).join(".");
      return `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ""}${classes ? `.${classes}` : ""}`;
    };
    const none = { src: null, carried: null, table: null, cols: null, row: null };
    const provenance = (start: Element) => {
      for (let el: Element | null = start; el; el = el.parentElement) {
        if (el.hasAttribute("data-src")) {
          return { ...none, src: el.getAttribute("data-src"), carried: el.getAttribute("data-value") };
        }
        if (el.hasAttribute("data-row")) {
          const holder = el.closest("[data-src-table]");
          return {
            ...none,
            table: holder?.getAttribute("data-src-table") ?? null,
            cols: holder?.getAttribute("data-src-cols") ?? null,
            row: el.getAttribute("data-row"),
          };
        }
      }
      return none;
    };

    // Figure, table and note marks, in document order (lists are checked apart).
    const markElements = [
      ...document.body.querySelectorAll('[data-structural]:not([data-structural="list"])'),
    ];
    const marks = markElements.map((el) => ({
      kind: el.getAttribute("data-structural") ?? "",
      text: el.textContent ?? "",
      where: describe(el),
      hasChildren: el.children.length > 0,
      citesData: el.closest("[data-src], [data-row]") !== null,
    }));

    const items: Item[] = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const text = node.textContent ?? "";
      const parent = node.parentElement;
      if (!parent || !/\d/.test(text) || parent.closest("script, style, noscript, template")) {
        continue;
      }
      const holder = parent.closest('[data-structural]:not([data-structural="list"])');
      const mark = holder ? markElements.indexOf(holder) : -1;
      items.push({
        text,
        where: describe(parent),
        ...provenance(parent),
        mark: mark >= 0 ? mark : null,
      });
    }
    for (const el of document.body.querySelectorAll("*")) {
      for (const name of attributes) {
        const value = el.getAttribute(name);
        if (value && /\d/.test(value)) {
          items.push({ text: value, where: `${describe(el)}[${name}]`, ...provenance(el), mark: null });
        }
      }
    }
    if (/\d/.test(document.title)) {
      items.push({ text: document.title, where: "title", ...none, mark: null });
    }

    // Numbered lists: every list item whose marker is a counter, grouped by list. Also every
    // element marked as a structural list, so a mark on something else is caught.
    const unnumbered = new Set(["none", "disc", "circle", "square", "disclosure-open", "disclosure-closed"]);
    const listElements = new Set<Element>(document.body.querySelectorAll('[data-structural="list"]'));
    for (const el of document.body.querySelectorAll("*")) {
      const style = getComputedStyle(el);
      if (style.display !== "list-item" || !el.parentElement) continue;
      const type = style.listStyleType;
      if (unnumbered.has(type) || type.startsWith('"')) continue;
      listElements.add(el.parentElement);
    }
    const lists = [...listElements].map((list) => ({
      where: describe(list),
      tag: list.tagName.toLowerCase(),
      structural: list.getAttribute("data-structural") === "list",
      start: list instanceof HTMLOListElement ? list.start : null,
      reversed: list instanceof HTMLOListElement && list.reversed,
      hasValues: [...list.children].some((child) => child.hasAttribute("value")),
    }));

    // Numbers in CSS-generated content cannot carry provenance: always refused.
    const generated: { text: string; where: string }[] = [];
    for (const el of document.body.querySelectorAll("*")) {
      for (const pseudo of ["::before", "::after"]) {
        const content = getComputedStyle(el, pseudo).content;
        if (content && content !== "none" && content !== "normal" && /\d/.test(content)) {
          generated.push({ text: content, where: `${describe(el)}${pseudo}` });
        }
      }
    }

    return {
      base: document.documentElement.dataset.dataBase ?? "",
      items,
      marks,
      lists,
      generated,
    };
  }, ATTRIBUTES);
}

export async function findUnsourcedNumbers(
  page: Page,
  request: APIRequestContext,
): Promise<NumberIssue[]> {
  const { base, items, marks, lists, generated } = await collect(page);
  const files = new Map<string, unknown>();
  const load = async (file: string) => {
    if (!files.has(file)) {
      const response = await request.get(`${base}${file}`);
      if (!response.ok()) throw new Error(`${base}${file}: HTTP ${response.status()}`);
      files.set(file, await response.json());
    }
    return files.get(file);
  };

  const structural = checkStructuralMarks(marks);
  const issues: NumberIssue[] = [
    ...structural.problems.map((problem) => ({ text: "", where: "", problem })),
    ...checkNumberedLists(lists).map((problem) => ({ text: "", where: "", problem })),
    ...generated.map(({ text, where }) => ({
      text,
      where,
      problem: "number in CSS-generated content",
    })),
  ];
  for (const item of items) {
    // A valid structural mark exempts only its own text, the "Figura N" itself.
    if (item.mark !== null && structural.valid[item.mark]) continue;
    let refs: Ref[];
    if (item.src !== null) refs = parseRefs(item.src);
    else if (item.row !== null && item.table !== null && item.cols !== null) {
      refs = rowRefs(item.table, item.cols, Number(item.row));
    } else {
      issues.push({ text: item.text, where: item.where, problem: "number without provenance" });
      continue;
    }
    const allowed = new Set<string>();
    try {
      for (const ref of refs) {
        for (const token of numberTokens(renderRef(ref, await load(ref.file), item.carried))) {
          allowed.add(token);
        }
      }
    } catch (error) {
      issues.push({ text: item.text, where: item.where, problem: String(error) });
      continue;
    }
    for (const token of numberTokens(item.text)) {
      if (!allowed.has(token)) {
        issues.push({
          text: item.text,
          where: item.where,
          problem: `${token} is not what ${refs.map(serializeRef).join("; ")} says`,
        });
      }
    }
  }
  return issues;
}
