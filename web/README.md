# Site do Atlas da Lavoura

Produto web estático (Astro 7 + ilhas React), construído a partir dos arquivos da camada
de servir dados. O contrato dos arquivos está em
[`docs/CONTRATO_DE_DADOS.md`](../docs/CONTRATO_DE_DADOS.md).

## Como rodar

```bash
cd web
npm ci
npm run setup   # baixa o pacote de dados do release (confere o sha256), gera os tipos e valida
npm run dev     # servidor de desenvolvimento
```

O `setup` lê o ponteiro [`data-release.json`](../data-release.json) da raiz do
repositório, baixa o tarball do release do GitHub, confere o sha256 e o tamanho, extrai
para `public/data/<versão>/` e gera os tipos TypeScript dos JSON Schemas de
`src/atlas_da_lavoura/serving/schemas/`. Nada disso é commitado.

## Identidade visual

`src/styles/tokens.css`, `src/styles/fonts.css` e `src/lib/tokens.ts` são **gerados** de
`src/atlas_da_lavoura/viz/identity.py` por `uv run python scripts/make_web_tokens.py`
(na raiz do repositório) e commitados; um teste no pytest falha se eles divergirem da
identidade. Não editar à mão. A tipografia tem três vozes da IBM Plex: Serif Regular nos
títulos e no parágrafo de abertura, Sans no texto e Mono (com o zero liso do `ss04`) nos
números, rótulos e metadados; só o número de destaque da página vai em Sans Bold
(`--font-display-number`). Os subsets Latin1 em woff2, só dos pesos usados, ficam em
`public/fonts/`, com a licença OFL. O fundo do site (`--color-background`, um branco quente)
e o das faixas de destaque (`--color-band`) também vêm da identidade.

## Números

Nenhum número de dado é escrito à mão. Cada um vem de um arquivo do pacote de dados e
cita a sua origem na marcação, por exemplo
`<data data-src="analysis.json#/headline/below_trend_share_all_years|pct">43%</data>`.
Nas páginas, use `sourced()` de `src/lib/sourced.ts` e o componente `Num`; nas tabelas, a
linha (`data-row`) com `data-src-table` e `data-src-cols` num elemento acima.

A numeração de figuras, tabelas e notas é estrutural: use o componente `Structural`
(`<Structural kind="figure" n={1} />` imprime "Figura 1"), com N na ordem em que aparece
na página. Listas numeradas são `<ol data-structural="list">`, contando a partir de 1. O
teste `e2e/analysis.spec.ts` (e `e2e/explore.spec.ts` para a legenda, o tooltip e a tabela do mapa; verificador em `e2e/provenance.ts`, regras em
`src/lib/structural.ts`) falha se um número de dado não tiver origem ou divergir do
arquivo, se uma marca estrutural fugir das regras ou se uma lista numerada não estiver
marcada.

## Qualidade

```bash
npm run check         # astro check (TypeScript estrito)
npm test              # Vitest (formatos, procedência, círculos e classes do mapa, geometria, busca, gráficos e hooks)
npm run build         # build de produção em dist/ (inclui as 5.571 páginas de município)
npm run e2e           # Playwright + axe (WCAG 2.x A/AA) e procedência dos números, nos dois temas
npm run lhci:desktop  # Lighthouse CI com orçamento por página (erro < 0,90)
npm run lhci:mobile   # idem no celular (Explorar: aviso < 0,80)
node scripts/measure-explore.mjs   # depois do build: tempos do mapa no celular simulado e no computador
```

O CI roda tudo isso em `.github/workflows/site.yml`, apenas quando `web/` ou o ponteiro
de dados mudam. O movimento reduzido é respeitado em duas camadas: a regra global de CSS
(técnica WCAG C39) e o hook `usePrefersReducedMotion`, que toda animação significativa
(linha do tempo do mapa) deve consultar; a linha do tempo nunca inicia sozinha
(WCAG 2.2.2).
