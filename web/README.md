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

`src/styles/tokens.css` e `src/lib/tokens.ts` são **gerados** de
`src/atlas_da_lavoura/viz/identity.py` por `uv run python scripts/make_web_tokens.py`
(na raiz do repositório) e commitados; um teste no pytest falha se eles divergirem da
identidade. Não editar à mão. As fontes IBM Plex Sans (woff2, subset Latin1, licença OFL)
estão em `public/fonts/`.

## Qualidade

```bash
npm run check         # astro check (TypeScript estrito)
npm test              # Vitest (componentes e hooks)
npm run build         # build de produção em dist/
npm run e2e           # Playwright + axe (WCAG 2.x A/AA), temas claro e escuro
npm run lhci:desktop  # Lighthouse CI com orçamento por página (erro < 0,90)
npm run lhci:mobile   # idem no celular (Explorar: aviso < 0,80)
```

O CI roda tudo isso em `.github/workflows/site.yml`, apenas quando `web/` ou o ponteiro
de dados mudam. O movimento reduzido é respeitado em duas camadas: a regra global de CSS
(técnica WCAG C39) e o hook `usePrefersReducedMotion`, que toda animação significativa
(linha do tempo do mapa) deve consultar; a linha do tempo nunca inicia sozinha
(WCAG 2.2.2).
