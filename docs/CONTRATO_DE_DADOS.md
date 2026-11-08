# Contrato dos dados do site

Este documento descreve os arquivos que o site lê: onde estão, o que cada um traz, o que cada valor significa e as regras que o site precisa seguir. O site é estático e não consulta o warehouse. Tudo o que ele mostra vem destes arquivos, gerados pela camada de servir dados (views `serve_*` do dbt e o comando `export-serving`; ver [DECISOES.md](DECISOES.md#camada-de-servir-dados-arquivos-estáticos-para-o-site)).

Os esquemas formais estão em [`src/agro_observatory/serving/schemas/`](../src/agro_observatory/serving/schemas/), em JSON Schema (Draft 2020-12) com descrições em português. Cada arquivo publicado é validado contra o seu esquema antes de ser gravado.

## Índice

- [Versões e localização](#versões-e-localização)
- [Convenções](#convenções)
- [Regras para o site](#regras-para-o-site)
- [Arquivos](#arquivos)
- [Regras de validade e como são garantidas](#regras-de-validade-e-como-são-garantidas)
- [Qualidade](#qualidade)
- [Fontes e atribuição](#fontes-e-atribuição)

## Versões e localização

- **Versão dos dados** (`data_version`): a data da geração, `AAAA.MM.DD`. Uma versão nunca muda depois de publicada.
- **Versão do esquema** (`schema_version`): um inteiro por tipo de arquivo. Ela muda quando o formato muda de forma incompatível, e o site deve conferi-la.
- **Publicação:** cada versão é um release do GitHub, `data-v<versão>`, com o pacote `site-data-<versão>.tar.gz` e o `manifest.json`.
- **Ponteiro:** o arquivo `data-release.json`, na raiz do repositório, fixa a versão que o site usa. Ele traz a tag, a URL do pacote, o sha256 e as versões dos esquemas. O build do site baixa o pacote, confere o sha256 e publica os arquivos em `/data/<versão>/`.
- **Ponto de entrada:** o primeiro arquivo que o site lê é `catalog.json`. O campo `files` dele traz o padrão de caminho de todos os outros.

Todo arquivo começa com um bloco `meta`:

| Campo | Conteúdo |
|---|---|
| `schema`, `schema_version` | tipo do arquivo e versão do esquema |
| `data_version` | versão dos dados |
| `generated_at` | data e hora da geração, em UTC |
| `sources` | chaves das fontes do arquivo; a atribuição de cada uma está em `catalog.json` |

## Convenções

- **`null` é "sem dado", 0 é zero.** `null` quer dizer que não há dado: o município não tinha linha na PAM naquele ano (por exemplo, ainda não existia), a variável não existia (a área plantada antes de 1988) ou o território não tem nenhum município com dado. 0 é um zero publicado pelo IBGE.
- **Arrays densos.** Toda série vem alinhada com uma lista explícita de anos consecutivos, com `null` onde não há dado; nenhum ano é omitido.
- **Valor real com anos próprios.** O valor real da produção existe só a partir de 1995 (ou do início da série, se for depois). Por isso ele vem num objeto à parte, `real_value`, com a sua própria lista de anos, em vez de `null` antes de 1995.
- **Ordem canônica.** Municípios em ordem crescente de código IBGE, a mesma em `municipalities.json`, nas linhas das matrizes de `explore/` e na malha.
- **Tabelas colunares.** Uma tabela é um objeto de arrays de mesmo tamanho (`{"year": [...], "hhi": [...]}`), não uma lista de objetos.
- **Séries publicadas** (campo `series`):

| Série | Conteúdo |
|---|---|
| `soybean`, `corn` | soja e milho, 1974 em diante |
| `coffee_in_husk` | café total em coco, 1974–2001 |
| `coffee_processed` | café total beneficiado, 2002 em diante |
| `coffee_arabica`, `coffee_canephora` | 2012 em diante, já beneficiados |

- **Unidades:**
  - **Produção:** toneladas, na unidade da série (`series.production_unit_pt` no catálogo).
  - **Áreas:** hectares. A área "plantada" é a área em produção no café.
  - **Valor real:** mil reais do ano-base (`parameters.deflation_base_year`), deflacionado pelo IPCA.
  - **Rendimento:** kg/ha; só aparece pronto nas tabelas analíticas.
- **Frações e percentuais:**
  - **Frações:** anomalias, participações, taxas de acerto, frequências e diferenças relativas. Por exemplo, −0,09 = 9% abaixo.
  - **Percentual:** só `precipitation_pct_of_normal` (45 = 45% da chuva normal).
  - **Z-scores:** desvios em relação à normal 1991–2020 do território.

## Regras para o site

1. **Agregados territoriais só dos arquivos.** O site nunca calcula agregados territoriais por conta própria além dos níveis que os arquivos trazem: Brasil, macrorregião, UF e região imediata. O único cálculo permitido no navegador é a razão produção ÷ área para o rendimento, sempre como soma ÷ soma:
   - num território, é `production_t ÷ harvested_area_ha × 1000` do próprio arquivo;
   - nunca é a média dos rendimentos dos municípios.
2. **Associação nunca por município.** Associação entre clima e rendimento só por região imediata e UF. Na página de um município, o risco de seca é o da sua região imediata (`places/region/<id>.json`, bloco `climate`), apresentado como da região.
3. **Café:**
   - nenhuma linha, comparação, variação ou animação junta `coffee_in_husk` e `coffee_processed`; o seletor de ano de uma série vai do `first_year` ao `last_year` dela;
   - o arábica e o canéfora só existem a partir de 2012.
4. **Clima:**
   - só para soja e café arábica, e só nos territórios que trazem o bloco `climate`;
   - os nomes das classes vêm de `catalog.climate_labels`, por exemplo "seca na floração e enchimento" na soja e "seca no enchimento dos grãos" no café;
   - o milho não tem clima.
5. **Sem dado aparece como sem dado.** `null` é mostrado como "sem dado", com cor e legenda próprias, nunca como zero.
6. **Neutralidade.** Nada marca governos nem mandatos. Os arquivos não trazem esse tipo de informação, e o site não deve acrescentá-la.
7. **Associação, não causalidade.** Os textos falam em anos que coincidem com quedas, nunca em quedas causadas pela seca.
8. **Atribuição.** Onde aparecem dados de uma fonte, o site exibe o texto `attribution_pt` dela, que está em `catalog.sources`.

## Arquivos

Os tamanhos com gzip abaixo são os da versão gerada em 2026-11-07, com os dados completos.

| Caminho | Esquema | Página | Quando carrega | gzip |
|---|---|---|---|---|
| `catalog.json` | catalog | todas | na abertura | 2 KiB |
| `municipalities.json` | municipalities | Município; Explorar (nomes) | na abertura; no Explorar, na primeira busca | 61 KiB |
| `analysis.json` | analysis | Análise | na abertura | 33 KiB |
| `method.json` | method | Método | na abertura | 8 KiB |
| `explore/<série>/<medida>.json` (24) | explore | Explorar | a soja na abertura; as demais ao trocar o filtro | 10 a 434 KiB (soja 189, milho 434) |
| `places/country.json` | place | Explorar, Município | na abertura | 4 KiB |
| `places/macro_region/<id>.json` (5) | place | — | sob demanda | 4 KiB |
| `places/state/<UF>.json` (27) | place | Município | ao escolher o município | 3 a 5 KiB |
| `places/region/<id>.json` (510) | place | Município | ao escolher o município | mediana 10 KiB, máximo 52 KiB |
| `geo/municipalities.topo.json` | topology | Explorar | na abertura | 290 KiB |
| `geo/states.topo.json` | topology | Análise | ao chegar à seção da fronteira | 13 KiB |
| `geo/state/<UF>.topo.json` (27) | topology | Explorar (zoom), Município (minimapa) | sob demanda | 1 a 151 KiB |
| `manifest.json` | manifest | — (auditoria e release) | — | — |

**`catalog.json`.** O ponto de entrada. Traz:
- `series`: a tabela das séries, com nomes, unidade, área e anos;
- `measures`: as medidas dos mapas;
- `parameters`: os parâmetros do método (ano-base, quebra do café, normal, limiares);
- `climate_labels`: os rótulos das classes por cultura;
- `sources`: a atribuição de cada fonte, com o período de referência;
- `files`: o padrão de caminho de cada arquivo;
- `null_means`, `municipality_count`, `warehouse` e `sample`.

**`municipalities.json`.** Traz quatro tabelas colunares:
- `municipalities`: código, nome, UF, região imediata e primeiro ano com dado na PAM (`null` nos 7 municípios sem dado);
- `states`;
- `immediate_regions`;
- `macro_regions`.

**`explore/<série>/<medida>.json`.** As medidas são `production_t`, `harvested_area_ha`, `planted_or_bearing_area_ha` e `production_value_real_thousand_brl`. O arquivo traz:
- `values`: a matriz, uma linha por município na ordem canônica e uma coluna por ano de `years`;
- `country_total`: o total do Brasil por ano, para a linha do tempo;
- `municipalities_with_data`: quantos municípios têm dado em cada ano.

Não há rendimento: o mapa de rendimento usa as matrizes de produção e de área colhida, célula a célula.

**`places/...`.** A ficha de um território:
- `territory`: nível, código, nome e UF.
- `series`: uma entrada por série publicada, com a produção, as áreas, os municípios com dado, os municípios produtores e o valor real.
- `climate`: presente nas UFs e regiões imediatas. Tem uma entrada por cultura com associação (`soybean`, `coffee_arabica`), formada por uma tabela por ano (`years`) e um `summary` com a frequência de anos de seca (`water_deficit_share`, o risco de seca), a anomalia média nos anos de seca e nos demais, a taxa de acerto e a correlação. Fica vazio onde não se aplica.
- `municipalities`: só nas regiões imediatas. Lista todos os municípios da região, cada um com as suas séries e os rankings por produção na região, na UF e no Brasil (`rank_immediate_region`, `rank_state`, `rank_country`; empates dividem a posição; `null` quando a produção é zero ou não há dado). Os totais de produtores para "X de Y" estão no `producing_municipalities` do território.

**`analysis.json`.** Traz:
- `headline`: o achado principal, com os UF-anos, as anomalias médias nos anos de seca e nos demais, as frações abaixo da tendência e as regiões com correlação positiva;
- `climate_yield_by_state` e `climate_summary_by_state`;
- `growth_decomposition`;
- `concentration`;
- `coffee_mg_biennial`;
- `soybean_frontier`: participações por UF e macrorregião, o centroide da produção por ano e os limiares de 1% e 5%.

**`method.json`.** Traz:
- `parameters`;
- `validation.sidra_summary`: células comparadas com os agregados do IBGE, por nível, variável e situação;
- `validation.sidra_discrepancies`: as células documentadas, com o motivo;
- `validation.conab`: a soja por UF e ano-safra, PAM contra Conab;
- `dbt_tests`: o resumo dos testes do build publicado.

**`geo/*.topo.json`.** TopoJSON padrão, para decodificar com `topojson-client`:
- **Coordenadas:** em graus (SIRGAS 2000), quantizadas, com `transform`.
- **Ids:** o `id` de cada geometria é o código IBGE do município, ou da UF em `states.topo.json`.
- **Sentido dos anéis:** os externos no sentido horário e os buracos no anti-horário, a convenção do d3-geo.
- **Fronteiras de UF no mapa nacional:** saem dos mesmos arcos, com `topojson.mesh` filtrando os pares de municípios de UFs diferentes.

## Regras de validade e como são garantidas

Cada regra do produto é garantida nos próprios dados, em três lugares:
1. **Nas views do dbt**, com filtros e testes que rodam a cada build.
2. **No contrato**, checado em cada arquivo antes de gravar.
3. **Na conciliação** com os marts.

| Regra | Nas views (dbt) | No contrato e na conciliação |
|---|---|---|
| Associação clima × rendimento só por região imediata e UF | `serve_climate_*` filtram esses dois níveis; `accepted_values` no nível | os registros de município têm esquema fechado (`additionalProperties: false`), sem campo de clima; uma varredura recusa nomes de clima, anomalia ou associação em arquivos municipais |
| Café sem séries que atravessem 2002 | as views usam a série publicada (macro `serve_series`); o teste `assert_serve_series_respect_coffee_break` confere todos os modelos com série e ano | os anos de cada série respeitam a quebra em todos os arquivos; `coffee_total` não aparece em nenhum |
| Café arábica separado só a partir de 2012 | o mesmo teste | os anos das séries `coffee_arabica` e `coffee_canephora` começam em 2012 |
| Clima só para soja e café | `accepted_values` na cultura; a associação só usa municípios produtores | os blocos de clima só aceitam `soybean` e `coffee_arabica` |
| Milho fora da análise climática | idem | idem |
| Sem dado aparece como sem dado, nunca como zero | o fato só tem linhas com dado; ausência é "sem dado" | arrays densos alinhados com os anos; a conciliação confere, por série, medida e ano, que os valores presentes são as linhas do fato, que os zeros são os zeros do fato e que o resto é `null` |
| Neutralidade | nenhum mart tem dimensão política | o esquema fechado impede campos não previstos |

## Qualidade

- **Testes do dbt nas views:** unicidade do grão, chaves, valores aceitos, a regra do café, a coerência dos rankings, os totais territoriais iguais à soma dos municípios, o centroide cobrindo toda a produção e o achado numa linha só.
- **Esquema e estrutura:** cada arquivo é validado contra o seu JSON Schema, e as tabelas colunares têm de ter colunas do mesmo tamanho.
- **Conciliação com os marts**, por consultas próprias, sem passar pelas views:
  - matrizes iguais ao fato;
  - Brasil igual ao fato;
  - UFs, macrorregiões e regiões somando o Brasil;
  - cada região igual à soma dos seus municípios;
  - o achado principal recalculado da associação;
  - as linhas de clima iguais às do mart;
  - a malha decodificada como cobertura válida com exatamente os municípios do índice.
  Qualquer falha impede a gravação.
- **CI:** a cada pull request, o CI exporta a amostra de 7 municípios com o mesmo código, valida e concilia. A amostra nunca é publicada.
- **Entre warehouses:** no evento de publicação, os arquivos gerados do BigQuery são comparados com os do Postgres (`scripts/compare_serving_bundles.py`).
- **Pacote:** `package-serving` só empacota uma exportação do BigQuery com todos os arquivos conferidos contra o manifesto.

## Fontes e atribuição

O texto de citação de cada fonte (`attribution_pt`), as condições de uso e o período de referência estão em `catalog.json`, gerados de [`src/agro_observatory/serving/sources.py`](../src/agro_observatory/serving/sources.py):

| Chave | Fonte | Condição |
|---|---|---|
| `ibge_pam`, `ibge_localities`, `ibge_mesh` | IBGE: PAM (tabela 5457), API de Localidades, malha municipal | domínio público, com a citação do IBGE |
| `bcb_ipca` | IPCA, do IBGE, obtido no SGS do Banco Central (série 433) | citação do IBGE e do SGS |
| `brdwgd` | BR-DWGD v3.2.4 | citação de Xavier et al. (2022), pedida pelos autores |
| `conab_calendar`, `conab_series` | Conab: calendário de plantio e colheita (2022), série histórica das safras | reprodução permitida com a citação da fonte |
