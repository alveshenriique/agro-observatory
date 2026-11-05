{% docs __overview__ %}

# Agro Observatory: modelos do dbt

Pipeline sobre a produção agrícola brasileira: Produção Agrícola Municipal (PAM) do IBGE para soja, milho e café (1974–2025), IPCA do Banco Central e clima diário em grade do BR-DWGD agregado por município. Este site documenta cada tabela, cada coluna e cada teste, com a linhagem entre elas (botão verde no canto inferior direito). O repositório, com o README, as decisões de engenharia, a metodologia e a validação, está em [github.com/alveshenriique/agro-observatory](https://github.com/alveshenriique/agro-observatory).

## Sobre os números deste site

Este site é gerado pelo CI a cada merge na `main` a partir da **amostra usada nos testes**, e não dos dados completos: a PAM de 7 municípios em todas as culturas e anos, o clima de 2023 a 2025 desses mesmos municípios, e Localidades e IPCA completos. Descrições, colunas, tipos, testes e linhagem são os mesmos nos dois casos, mas qualquer contagem ou estatística mostrada aqui se refere à amostra. Na amostra, os z-scores climáticos ficam nulos, porque a normal de 1991–2020 não existe nela.

Volumes com os dados completos (ingeridos em setembro de 2026), em linhas:

- `raw.pam`: 5.118.880 (amostra: 6.440)
- `raw.brdwgd_municipality_daily`: 93.603.942 (amostra: 7.672)
- `raw.localities`: 5.571 e `raw.ipca`: 560 (completos também na amostra)
- `int_pam__crop_year`: 1.023.776
- `int_climate__window_indicators`: 350.280
- `int_climate__window_normals`: 7.784
- `int_yield__territory_trend`: 14.130
- `dim_municipality`: 5.571
- `fct_crop_production`: 925.986
- `fct_crop_climate`: 83.290
- `agg_climate_yield_association`: 12.666
- `agg_climate_yield_association_summary`: 278

## Como ler

As tabelas estão em três camadas, identificadas pelo prefixo:

- **`stg_` (staging)**: a camada raw tipada e renomeada, sem joins nem regras de negócio. Um modelo por fonte e entidade: `stg_ibge__pam`, `stg_ibge__localities`, `stg_bcb__ipca`, `stg_brdwgd__municipality_daily`, `stg_brdwgd__municipality_cells`.
- **`int_` (intermediate)**: cálculos intermediários reutilizados pelos marts: o pivô da PAM por município × cultura × ano, o índice anual do IPCA, os indicadores climáticos por janela e as suas normais, e a tendência de rendimento por território.
- **marts**: o modelo dimensional (`fct_crop_production`, `fct_crop_climate`, `dim_municipality`, `dim_crop`, `dim_year`) e os marts analíticos `agg_*`, que respondem às perguntas de negócio e são a fonte do dashboard.

Os seeds (`crops`, calendários da Conab, eventos climáticos conhecidos, agregados oficiais do IBGE e série da Conab) são dados pequenos versionados no repositório.

## Por onde começar

- `fct_crop_production`: uma linha por município × cultura × ano, com área, produção, rendimento e valor (nominal e a preços de 2025). Somas entre culturas devem excluir o detalhamento do café (`dim_crop.is_coffee_breakdown`), e as séries de café não devem atravessar 2002 (`dim_year.is_coffee_processed_unit`).
- `fct_crop_climate`: clima por município × cultura × ano da colheita, nas janelas fenológicas de cada cultura, com anomalias (z-scores) contra a normal 1991–2020 do próprio município.
- `agg_climate_yield_association` e `agg_climate_yield_association_summary`: a associação entre as anomalias climáticas e a anomalia de rendimento por região imediata e UF. Associação, não causalidade.
- `agg_production_growth_decomposition`, `agg_production_share_by_territory`, `agg_territory_share_thresholds`, `agg_production_concentration`, `agg_coffee_mg_biennial`: as demais perguntas de negócio (área × produtividade, fronteira agrícola, concentração, bienalidade do café).

Os testes aparecem em cada modelo. Todos são invariantes (valem para qualquer recorte dos dados), por isso rodam também no CI com uma amostra de 7 municípios; os que comparam com totais oficiais passam vazios na amostra.

{% enddocs %}
