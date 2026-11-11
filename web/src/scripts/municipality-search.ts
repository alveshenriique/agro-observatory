// Municipality search with autocomplete (ARIA 1.2 combobox with a listbox popup). The
// index, municipalities.json from the data package, loads on the first focus of the field,
// so the page itself does not pay for it. Choosing a municipality opens its page.
import { buildIndex, type MunicipalityIndex, search, type SearchEntry } from "../lib/search";

const LIMIT = 8;

// The long hint ("Sorriso, Rio Verde, Patrocínio…") only where it fits whole; a narrow field
// (a phone, or the band's right column on a tablet) gets the short one instead of an ellipsis.
function fitPlaceholder(input: HTMLInputElement): void {
  const long = input.placeholder;
  const short = input.dataset.placeholderShort;
  const context = document.createElement("canvas").getContext("2d");
  if (!short || !context) return;
  const fit = () => {
    const style = getComputedStyle(input);
    context.font = `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
    const room = input.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    input.placeholder = context.measureText(long).width <= room ? long : short;
  };
  fit();
  void document.fonts.ready.then(fit);
  new ResizeObserver(fit).observe(input);
}

function setup(form: HTMLFormElement): void {
  const input = form.querySelector<HTMLInputElement>('input[role="combobox"]');
  const list = form.querySelector<HTMLUListElement>('[role="listbox"]');
  const status = form.querySelector<HTMLElement>("[data-status]");
  const url = form.dataset.index;
  if (!input || !list || !status || !url) return;
  fitPlaceholder(input);

  let loading: Promise<SearchEntry[]> | null = null;
  let options: SearchEntry[] = [];
  let active = -1;

  const load = () =>
    (loading ??= fetch(url)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json() as Promise<{ municipalities: MunicipalityIndex }>;
      })
      .then((data) => buildIndex(data.municipalities)));

  const go = (entry: SearchEntry | undefined) => {
    if (entry) window.location.assign(`/municipio/${entry.id}/`);
  };

  const highlight = (index: number) => {
    active = index;
    list.querySelectorAll<HTMLElement>('[role="option"]').forEach((option, i) => {
      option.setAttribute("aria-selected", String(i === index));
    });
    const option = index >= 0 ? list.children[index] : undefined;
    if (option) {
      input.setAttribute("aria-activedescendant", option.id);
      option.scrollIntoView({ block: "nearest" });
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  };

  const close = () => {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    highlight(-1);
  };

  const render = (results: SearchEntry[]) => {
    options = results;
    list.replaceChildren(
      ...results.map((entry, i) => {
        const option = document.createElement("li");
        option.id = `${list.id}-${i}`;
        option.setAttribute("role", "option");
        option.setAttribute("aria-selected", "false");
        const state = document.createElement("span");
        state.className = "search__state mono";
        state.textContent = entry.state;
        option.append(`${entry.name} `, state);
        option.addEventListener("mousedown", (event) => event.preventDefault());
        option.addEventListener("click", () => go(entry));
        return option;
      }),
    );
    list.hidden = results.length === 0;
    input.setAttribute("aria-expanded", String(results.length > 0));
    highlight(-1);
    status.textContent =
      results.length > 0
        ? "Sugestões disponíveis. Use as setas para escolher e Enter para abrir."
        : input.value.trim() === ""
          ? ""
          : "Nenhum município encontrado.";
  };

  input.addEventListener("focus", () => void load().catch(() => undefined), { once: true });
  input.addEventListener("input", async () => {
    try {
      render(search(await load(), input.value, LIMIT));
    } catch {
      status.textContent = "Não foi possível carregar a lista de municípios.";
    }
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (options.length === 0) return;
      event.preventDefault();
      if (list.hidden) {
        list.hidden = false;
        input.setAttribute("aria-expanded", "true");
      }
      const step = event.key === "ArrowDown" ? 1 : -1;
      highlight((active + step + options.length) % options.length);
    } else if (event.key === "Enter" && active >= 0) {
      // Otherwise Enter submits the form, like "Abrir ficha".
      event.preventDefault();
      go(options[active]);
    } else if (event.key === "Escape") {
      if (!list.hidden) close();
      else input.value = "";
    }
  });
  input.addEventListener("blur", close);
  // "Abrir ficha" (or Enter): the highlighted suggestion, else the best match for the text,
  // even when the index is still loading.
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (active >= 0) return go(options[active]);
    try {
      go(search(await load(), input.value, LIMIT)[0]);
    } catch {
      status.textContent = "Não foi possível carregar a lista de municípios.";
    }
  });
}

for (const form of document.querySelectorAll<HTMLFormElement>("[data-municipality-search]")) {
  setup(form);
}
