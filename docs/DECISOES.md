# Decisões de engenharia

Este documento registra as decisões técnicas do pipeline do Atlas da Lavoura, cada uma com as alternativas descartadas e o motivo, para que possam ser defendidas e revistas. O critério para uma decisão entrar aqui é ser algo que uma pessoa técnica questionaria (arquitetura, carga, CI, portabilidade, desempenho, identidade visual). O lado analítico (como os números são calculados) está em [METODOLOGIA.md](METODOLOGIA.md) e a auditoria (validação externa, sensibilidade e correções) em [VALIDACAO.md](VALIDACAO.md).

## Índice

- [Stack do MVP](#stack-do-mvp)
- [Reingestão dos anos mais recentes da PAM](#reingestão-dos-anos-mais-recentes-da-pam)
- [Localidades como snapshot da malha atual](#localidades-como-snapshot-da-malha-atual)
- [Carga da camada raw no Postgres](#carga-da-camada-raw-no-postgres)
- [CI com amostra dos dados](#ci-com-amostra-dos-dados)
- [Clima: BR-DWGD agregado por município](#clima-br-dwgd-agregado-por-município)
- [SQL portável no dbt: um código para Postgres e BigQuery](#sql-portável-no-dbt-um-código-para-postgres-e-bigquery)
- [Nested loop desligado no modelo de janelas climáticas](#nested-loop-desligado-no-modelo-de-janelas-climáticas)
- [Identidade visual](#identidade-visual)
- [BigQuery em produção: sandbox e arquitetura enxuta](#bigquery-em-produção-sandbox-e-arquitetura-enxuta)
- [Operação do BigQuery: recarga e consumo de cota](#operação-do-bigquery-recarga-e-consumo-de-cota)
- [Camada de servir dados: arquivos estáticos para o site](#camada-de-servir-dados-arquivos-estáticos-para-o-site)

## Stack do MVP

A ingestão é feita em Python 3.12, com ambiente e dependências gerenciados pelo uv. Os dados brutos das APIs são salvos primeiro em arquivos Parquet (camada raw) e só depois carregados em um PostgreSQL local, rodando em Docker, que funciona como warehouse de desenvolvimento. As transformações até o modelo dimensional ficam no dbt-core. A camada raw em arquivo permite reprocessar e auditar os dados sem chamar as APIs de novo, e deixa a carga idempotente. O Parquet foi escolhido por preservar os tipos e ocupar pouco espaço.

Alternativas descartadas. DuckDB é mais simples, mas o PostgreSQL tem conexão nativa com o Power BI e fica mais próximo de um warehouse real, o que facilita a migração futura para cloud. pip e Poetry perderam para o uv, que reúne lockfile, gestão da versão do Python e muito mais velocidade numa única ferramenta. Gravar com pandas direto no banco, sem camada raw, acoplaria extração e carga e obrigaria a baixar tudo de novo das APIs a cada erro ou mudança de schema. CSV foi descartado por não preservar tipos. SQL avulso no lugar do dbt perderia a linhagem, os testes de dados e a documentação que o dbt já oferece.

## Reingestão dos anos mais recentes da PAM

A ingestão da PAM é idempotente: cada combinação de cultura e ano vira uma partição Parquet, e partições já existentes são puladas. A exceção são os 2 anos mais recentes disponíveis, que são sempre baixados de novo e sobrescritos. O IBGE revisa os dados da PAM depois da primeira divulgação, então pular esses anos congelaria números preliminares. O "ano mais recente" vem da API de metadados do IBGE a cada execução, e não de um valor fixo no código. Existe também a opção `--force`, que baixa tudo de novo.

Alternativas descartadas. Pular toda partição existente deixaria a camada raw desatualizada sem nenhum aviso. Baixar tudo a cada execução garante dados atualizados, mas custa 184 requisições (de 30 a 60 minutos) para mudar, na prática, só os anos recentes. Comparar hashes do conteúdo exigiria baixar os dados de qualquer forma, então não economizaria requisições.

## Localidades como snapshot da malha atual

A lista de municípios, com UF, região, mesorregião/microrregião e região intermediária/imediata, é baixada da API de Localidades do IBGE como uma foto da malha territorial atual. Cada execução substitui a anterior, sem guardar versões. Isso funciona porque a PAM também publica toda a série histórica na malha atual (municípios criados depois aparecem como "..." nos anos anteriores), então os dois lados do cruzamento usam a mesma referência territorial.

Alternativas descartadas. Guardar um histórico da malha (dimensão de mudança lenta, tipo 2) só teria valor se os fatos viessem em malhas diferentes a cada ano, o que não acontece aqui. O custo é que, se o IBGE redesenhar uma divisão regional, a mudança vale retroativamente para toda a série. Para acompanhar a evolução da malha seria preciso ingerir as tabelas de alterações territoriais do IBGE, o que foge do escopo do MVP.

## Carga da camada raw no Postgres

Cada arquivo Parquet é carregado no schema `raw` com `COPY`, numa transação própria. Na PAM, a transação apaga as linhas daquela partição (cultura e ano) e copia o arquivo. Em Localidades e IPCA, a tabela é esvaziada e recarregada. Se a carga falhar no meio, a transação é desfeita e o banco continua com a versão anterior completa. Para não recarregar 5 milhões de linhas a cada execução, o `_ingested_at` de cada arquivo é comparado com o que já está no banco, e só os arquivos reingeridos desde a última carga são recarregados; `--force` recarrega tudo. Linhas de arquivos que não existem mais no disco geram um aviso na carga e só são apagadas com `--prune`, para que um arquivo removido por engano não apague dados do banco em silêncio. As tabelas raw não têm índices, chaves nem tipagem: isso é papel do dbt.

Alternativas descartadas. `pandas.to_sql` e inserts linha a linha são uma ou duas ordens de grandeza mais lentos que `COPY` e, no caso do pandas, trariam uma dependência só para isso. Um índice em `_source_file` aceleraria o `DELETE` por partição, mas a raw deve ficar sem índices, e com a carga pulando arquivos inalterados o `DELETE` só roda nas poucas partições que mudaram. Comparar hashes do conteúdo seria mais preciso do que comparar `_ingested_at`, mas exigiria ler cada arquivo inteiro a cada execução, e o `_ingested_at` já muda exatamente quando a ingestão regrava um arquivo.

## CI com amostra dos dados

O CI (GitHub Actions) roda em pull requests e em push na `main`, em dois jobs. O primeiro roda o ruff e o pytest. O segundo sobe um PostgreSQL descartável como service container, carrega uma amostra da camada raw com o carregador real (`load-raw`) e roda o `dbt build` completo, com todos os modelos e testes. A amostra fica versionada em `tests/fixtures/raw/`, no mesmo formato de `data/raw/`, e é regerada a partir dos dados reais por `scripts/make_ci_sample.py`. Ela tem a PAM completa (todas as culturas e anos) de 7 municípios escolhidos para cobrir os casos que os modelos precisam tratar: Sorriso-MT, Patrocínio-MG (arábica e bienalidade), Boa Esperança do Norte-MT (sem microrregião, dado só em 2025), Areias-SP (um dos rendimentos de 1998 publicados como "-"), Cascavel-PR, Luís Eduardo Magalhães-BA (desmembrado em 2000) e Cacoal-RO (café canephora). Localidades e IPCA vão completos, porque são pequenos.

Todos os testes do dbt rodam no CI sem exceção, porque foram escritos como invariantes (regras que valem para qualquer subconjunto dos dados): unicidade do grão, relações entre fato e dimensões, a decomposição que fecha, participações que somam 100%, arábica mais canephora igual ao total. Nenhum teste compara com um total nacional publicado, que só valeria com os dados completos. O teste de rendimento com severidade `warn` aparece no CI com 1 caso (Areias-SP em 1998), o que também confirma que o caminho de aviso continua funcionando. Os números da amostra (participações, concentração) não têm significado analítico: o CI verifica que o pipeline funciona e que as regras se mantêm, não os resultados.

As actions do workflow são fixadas pelo SHA do commit da release, com a versão num comentário ao lado (por exemplo, `actions/checkout@3d3c42e… # v7.0.1`), e não por uma tag como `v7`. Tags no Git podem ser movidas para outro commit, de propósito ou por um ataque à conta de quem mantém a action; um SHA não pode. Assim, o código que roda no CI é exatamente o que foi revisado, e uma atualização de versão é sempre uma mudança explícita no workflow. As versões e os SHAs foram conferidos nas tags publicadas de cada repositório. Isso também evita um problema real: nem toda action publica uma tag de versão major (o `astral-sh/setup-uv` só publica tags completas, como `v10.2.0`). Para que os SHAs não fiquem velhos, o Dependabot (`.github/dependabot.yml`) verifica as actions toda semana e abre um PR que atualiza o SHA e o comentário de versão juntos, passando pelo CI antes do merge.

Todo job dos três workflows (`ci.yml`, `docs.yml` e `site.yml`) tem `timeout-minutes`, porque o padrão do GitHub é 360 minutos e um passo travado só apareceria horas depois. O teto de cada job fica em cerca de três vezes a sua execução mais lenta recente, com mínimo de 5 minutos, e os passos que dependem de rede (`uv sync`, `npm ci`, `dbt deps`, os downloads e as actions do Pages) têm limites menores. A restauração dos caches desiste de um segmento travado em 2 minutos (`SEGMENT_DOWNLOAD_TIMEOUT_MINS`, em vez dos 10 do padrão) e segue sem cache. O deploy do Pages usa o timeout da própria action, de 6 minutos, abaixo do teto do job: assim a publicação é cancelada de forma limpa, em vez de o job ser morto no meio da consulta ao status.
**CI com a amostra.** Com clima de 2023 a 2025 para 7 municípios, só as colheitas de 2024 e 2025 têm janelas completas; a de 2023 fica com cobertura parcial e indicadores nulos, o que exercita a regra de completude. A normal de 1991–2020 não existe na amostra, então os z-scores ficam nulos e `is_normal_available` é falso; a tendência de rendimento existe, porque a PAM da amostra é completa. Todos os testes são invariantes condicionados a essas flags, e os de eventos conhecidos passam vazios. Nenhum modelo ou teste fica fora do CI.
Alternativas descartadas. Baixar os dados reais das APIs a cada execução do CI deixaria o build lento (cerca de 25 minutos só para a PAM) e dependente da disponibilidade do IBGE e do BCB. Criar dados sintéticos à mão testaria só os casos imaginados, enquanto a amostra real traz as esquisitices da fonte. Pular os testes que "precisam de dados completos" não foi necessário, porque nenhum precisa.

## Clima: BR-DWGD agregado por município

Os dados climáticos vêm do **BR-DWGD** (Brazilian Daily Weather Gridded Data), **versão v3.2.4** (grafada `v_3.2.4` nos nomes dos arquivos da fonte, e assim registrada na coluna `_source_version` dos Parquet), uma grade diária de 0,1° × 0,1° (cerca de 11 km) interpolada a partir de estações meteorológicas e pluviômetros de todo o país. São usadas quatro variáveis: chuva, temperatura máxima, temperatura mínima e evapotranspiração de referência (ETo), de 1980 a 2025. A página e o repositório do autor pedem a citação abaixo e não declaram uma licença; o catálogo comunitário do Google Earth Engine lista os dados sob CC BY 4.0.

> Xavier, A. C., Scanlon, B. R., King, C. W., & Alves, A. I. (2022). New improved Brazilian daily weather gridded data (1961–2020). *International Journal of Climatology*, 42(16), 8390–8404. https://doi.org/10.1002/joc.7731

Cada município recebe a média das células cujo centro cai dentro do seu polígono, pela malha municipal do IBGE (qualidade máxima). Quando nenhum centro cai dentro, o que acontece com municípios pequenos, usa-se a célula que contém o ponto representativo do polígono (um ponto que sempre fica dentro dele). Se essa célula não tem dado, porque cai no mar, usa-se a célula com dado mais próxima, até 0,2°; mais longe que isso, o município fica sem dado. Na malha atual, 5.304 municípios usam células internas, 259 o ponto representativo, 7 municípios litorâneos a célula vizinha e 1 fica sem dado (Fernando de Noronha, fora da grade). O método de cada município fica registrado em `raw.brdwgd_municipality_cells`. Os arquivos NetCDF não são baixados inteiros: o índice dos zips no Google Drive é lido com requisições HTTP Range, e só as quatro variáveis usadas são extraídas (8,5 GB baixados em vez de 9,9 GB).

Para a ingestão ser reprodutível, o SHA-256 de cada um dos 12 arquivos NetCDF usados fica versionado em `checksums/brdwgd_v3.2.4.sha256`, no formato do `sha256sum`. Cada arquivo é conferido contra esse manifesto ao ser baixado (antes de receber o nome final) e antes de ser lido pela agregação; se algum hash não bater, ou se aparecer um arquivo que não está no manifesto, a ingestão falha. Assim, uma republicação silenciosa da grade pelo autor não entra nos dados sem ser notada, e adotar uma versão nova é uma mudança explícita: novo manifesto e nova versão.

**Download manual, se a leitura parcial do zip parar de funcionar.** O download automático depende de o Google Drive aceitar requisições HTTP Range no link direto dos zips. Se isso mudar:

1. Baixe pelo navegador, na [pasta oficial do BR-DWGD no Google Drive](https://drive.google.com/drive/folders/11-qnvwojirAtaQxSE03N0_SUrbcsz44N), os arquivos `pr_Tmax_Tmin_NetCDF_Files.zip` (7,7 GB) e `ETo_u2_RH_Rs_NetCDF_Files.zip` (2,2 GB). A [página do autor](https://sites.google.com/site/alexandrecandidoxavierufes/brazilian-daily-weather-gridded-data) também aponta uma cópia dos NetCDF sem compressão no Dropbox e no Google Earth Engine.
2. Extraia só os 12 arquivos listados em `checksums/brdwgd_v3.2.4.sha256` (variáveis `pr`, `Tmax`, `Tmin` e `ETo`, três períodos cada) para `data/external/brdwgd/`. Por exemplo: `unzip -j pr_Tmax_Tmin_NetCDF_Files.zip 'pr_*' 'Tmax_*' 'Tmin_*' -d data/external/brdwgd/` e `unzip -j ETo_u2_RH_Rs_NetCDF_Files.zip 'ETo_*' -d data/external/brdwgd/`.
3. Confira os hashes: `(cd data/external/brdwgd && sha256sum -c ../../../checksums/brdwgd_v3.2.4.sha256)`.
4. Rode a agregação sem baixar: `uv run ingest-brdwgd --skip-download`. Os hashes são conferidos de novo antes da leitura.

A tabela município × dia (93,6 milhões de linhas) é uma exceção à regra de manter a camada raw em texto: suas colunas são tipadas (inteiro, data e real) no Parquet e no Postgres. Ela não é uma cópia do que a fonte entregou, e sim o resultado de uma agregação espacial feita pelo projeto, então não há um "texto original" a preservar, e guardar números como texto multiplicaria o tamanho sem ganho de auditoria. No Postgres, a tabela usa particionamento nativo por ano (uma partição por arquivo anual). Recarregar um ano é um `TRUNCATE` da partição seguido de `COPY`, numa transação, e leva cerca de 4 segundos, contra minutos de um `DELETE` numa tabela desse tamanho. Os metadados de carga (`_ingested_at`, arquivo de origem, horário da carga) ficam uma vez por arquivo na tabela de controle `raw._load_manifest`, em vez de repetidos em cada linha, o que economizaria vários gigabytes.

Alternativas descartadas. As estações do INMET dão o dado medido, sem interpolação, mas são esparsas justamente onde a produção se concentra (51 estações automáticas operantes para o Mato Grosso, com 29% da soja), começam em 2000 e mudam de formato em 2019. O ERA5-Land tem a mesma resolução, mas é uma reanálise de modelo, com viés conhecido de chuva nos trópicos, e exige conta no Copernicus. O NASA POWER tem uma API simples, mas uma célula de 0,5° × 0,625° (cerca de 55 × 70 km) é grossa demais para municípios. A média ponderada pela área de interseção de cada célula com o polígono seria um pouco mais precisa que "centro dentro do polígono", mas exigiria bibliotecas geoespaciais pesadas (GDAL), com ganho pequeno numa grade de 0,1°.

As limitações da grade interpolada para a análise (suavização de extremos, densidade variável de estações, média por município) estão em [METODOLOGIA.md](METODOLOGIA.md#limitações-dos-dados-climáticos-em-grade).

## SQL portável no dbt: um código para Postgres e BigQuery

A partir da fase 10 o projeto roda em dois warehouses: o PostgreSQL local continua como ambiente de desenvolvimento e de CI, e o BigQuery passa a ser a produção. Os modelos do dbt são um só código para os dois, escrito no SQL que os dois dialetos compartilham mais as macros cross-database do próprio dbt (`type_int`, `type_string`, `bool_or`, `except`, `datediff`, `last_day`, `date_trunc`; `generate_series` do dbt_utils) e quatro macros próprias em `dbt/macros/cross_database.sql`, que escolhem a forma certa pelo adapter (`adapter.dispatch`): `source_column` (nome de coluna da raw: entre aspas no Postgres, onde os nomes das APIs são case-sensitive e têm hífen; no BigQuery, que não aceita hífen, o hífen vira `_`, o mesmo rename que o carregador fará), `regex_match` (`~` ou `REGEXP_CONTAINS`), `parse_date` (`to_date` ou `PARSE_DATE`, com formato em notação `%d/%m/%Y`) e `date_from_parts` (`make_date` ou `DATE(ano, mês, dia)`; a macro `dbt.date()` só aceita literais).

As trocas foram mecânicas, mas algumas merecem registro. `filter (where ...)` virou `case when` dentro das agregações, que é equivalente e universal. A inclinação da tendência de rendimento deixou de usar `regr_slope`/`regr_intercept` (que o BigQuery não tem) e passou a `covar_pop(ln y, ano) ÷ var_pop(ano)`, com a reta avaliada em torno das médias; é a mesma reta, com diferença apenas no último dígito de ponto flutuante. `generate_series(a, b)` com limites vindos de uma consulta virou o `generate_series(n)` do dbt_utils (uma série fixa de números, montada por `union all` e `cross join`) recortada pelos limites, com cast de volta para inteiro, porque a série do dbt_utils sai como ponto flutuante. Os dias de cada mês, antes `make_date(...) + interval '1 month - 1 day'`, agora são `extract(day from last_day(...))`. A técnica de gaps-and-islands, que subtraía um número de uma data, passou a subtrair de um número de dias desde 1970-01-01, para não depender de aritmética de datas. `unnest(array[...])` virou `union all` de literais gerado pelo Jinja. `%` virou `mod()` e a divisão inteira `ano / 10 * 10` virou `div(ano, 10) * 10`, porque no BigQuery `/` entre inteiros devolve ponto flutuante. O `pre_hook` que aumenta o `work_mem` do Postgres só é emitido quando `target.type` é `postgres`. Os casts para numérico usam `numeric` literal, e não `dbt.type_numeric()`, porque no Postgres essa macro vira `numeric(28,6)`, o que mudaria a escala das divisões e, com ela, os últimos dígitos de rendimentos e participações; `numeric` sem precisão existe nos dois dialetos. Os `+column_types` dos seeds (`integer`, `numeric`) também são aceitos pelos dois.

**Validação do porte.** Antes de mudar qualquer modelo, as 18 tabelas dos schemas `marts`, `intermediate` e `staging` foram copiadas para um schema de referência; depois do `dbt build` completo com o SQL portável, cada tabela foi comparada com a cópia linha a linha, nos dois sentidos (`except all`), pelo script `scripts/compare_dbt_baseline.sql`. Treze tabelas são idênticas byte a byte, entre elas o fato de produção (925.986 linhas), o pivô da PAM (1.023.776), os indicadores de janela (350.280) e todos os agregados de produção. As outras cinco (`int_climate__window_normals`, `fct_crop_climate`, `int_yield__territory_trend`, `agg_climate_yield_association` e o seu `_summary`) têm as mesmas linhas no mesmo grão, nenhuma diferença em colunas inteiras, de texto ou booleanas (as classes de estresse não mudam), e diferenças só no último dígito de ponto flutuante: no máximo 1e-14 relativo nas normais e nos z-scores, e 1e-9 na anomalia de rendimento, que é uma razão próxima de zero. Duas causas, ambas esperadas: médias e desvios de `double precision` dependem da ordem física das linhas, que mudou com o plano de execução, e a inclinação da tendência passou de `regr_slope` para `covar_pop ÷ var_pop`. O projeto também foi compilado para o BigQuery sem conta nenhuma, com o adapter instalado de forma temporária e uma chave de service account falsa gerada localmente: isso confere que as macros renderizam SQL do dialeto certo, não que o BigQuery o aceita. A execução real no BigQuery veio na fase 10b (ver [BigQuery em produção](#bigquery-em-produção-sandbox-e-arquitetura-enxuta)), e achou um erro de dialeto e uma diferença de precisão que a compilação não pega.

Alternativas descartadas. Manter dois conjuntos de SQL (um por warehouse, com `{% if target.type == ... %}` em cada modelo) duplicaria regras e testes e deixaria os dois divergirem com o tempo. Ficar só no Postgres e levar o próprio Postgres para a cloud (Cloud SQL, AlloyDB) evitaria o porte, mas esses serviços não têm camada gratuita permanente e o objetivo da fase é justamente operar um warehouse colunar. Transpilar o SQL no build com uma ferramenta como o sqlglot esconderia as diferenças de dialeto de quem lê o código e acrescentaria uma dependência no caminho crítico do build.

## Nested loop desligado no modelo de janelas climáticas

O modelo `int_climate__window_indicators` tem, no Postgres, um segundo `pre_hook` além do `work_mem`: `set enable_nestloop = off`, válido só para a sessão daquele `CREATE TABLE`. A causa raiz é uma estimativa de cardinalidade errada: o planejador não tem estatísticas sobre a CTE `assigned` (cada dia de cada município produtor atribuído às janelas que contêm o seu mês) e estima o cruzamento `producing × calendar` em 87 linhas, quando são 40.320; a CTE inteira é estimada em 22 mil linhas, contra 55 milhões reais, e o resultado final em 1 linha, contra 350 mil. Com estimativas assim, o último join do modelo (as duas agregações da CTE, a dos indicadores e a do maior veranico) parece caber num nested loop, que varre uma tabela hash de 350 mil entradas uma vez por linha externa: mais de uma hora, contra cerca de 4 minutos com o hash join. O plano com hash join era o escolhido até o porte da fase 10a; a troca de `generate_series` pela série do dbt_utils mudou a estimativa de uma CTE pequena em 0,07% do custo total e bastou para o planejador mudar de ideia.

O ajuste de sessão contorna o sintoma: com nested loops desligados, o planejador volta aos hash joins em todos os joins do modelo, e os nested loops só ficam onde são a única opção (a série de números e o `cross join` com a CTE de uma linha). Ele não corrige a estimativa, que continua errada, e por isso é restrito a este modelo e a este banco, com o motivo em comentário no próprio modelo. Não é uma prática geral: desligar o nested loop num banco inteiro, ou por hábito, troca um plano ruim aqui por planos ruins em consultas pequenas, onde o nested loop é o certo. As alternativas seriam reescrever o modelo sem o join (união das duas agregações e `group by`), que não protegeria o join seguinte, ou criar estatísticas estendidas, que o Postgres não tem para junções entre tabelas.

## Identidade visual

**Base.** As cores dos dados seguem o guia visual do IPCC para o AR6 ([IPCC AR6 WGI Visual Style Guide, 2022](https://www.ipcc.ch/site/assets/uploads/2022/09/IPCC_AR6_WGI_VisualStyleGuide_2022.pdf)) e as escalas oficiais publicadas pelo próprio grupo de trabalho no repositório [IPCC-WG1/colormaps](https://github.com/IPCC-WG1/colormaps). O guia associa tons marrom-amarelados à seca, o azul à água e ao frio e o vermelho ao calor (página 10 do PDF). Ele também pede escalas divergentes de dois matizes com o centro claro e desaconselha usar azul com roxo ou verde com vermelho quando um gráfico tem mais de uma escala (página 12). Para chuva e balanço hídrico, indica a escala divergente `prec_div`, do marrom ao verde-azulado; para temperatura, a `temp_div`, do azul ao vermelho, as duas do ColorBrewer (página 13). A seca é a cor principal do projeto. O repositório do IPCC não declara licença; as duas escalas são de Brewer, Harrower e Penn State (2002), creditados no guia, e o projeto usa os valores de cor com essa atribuição.

**Paleta.** Cada papel tem uma variante para o fundo claro do GitHub (#ffffff) e outra para o escuro (#0d1117), sempre tiradas da mesma escala oficial: um dos 11 passos discretos ou uma posição da escala contínua de 256 tons (índice 0 a 255 nos arquivos `prec_div.txt` e `temp_div.txt`).

| Papel | Claro | Contraste | Escuro | Contraste | Origem |
|---|---|---|---|---|---|
| Seco (cor principal) | `#895819` | 6,05:1 | `#a36c22` | 4,26:1 | `prec_div`, passo 2 de 11 (contínua 26) e contínua 38 |
| Úmido | `#1a695f` | 6,50:1 | `#7cbab5` | 8,60:1 | `prec_div`, passo 10 de 11 (contínua 229) e contínua 176 |
| Quente | `#67001f` | 13,15:1 | `#de8475` | 6,91:1 | `temp_div`, passo 11 de 11 (contínua 255) e contínua 186 |
| Frio (geada) | `#4393c3` | 3,39:1 | `#3379aa` | 4,02:1 | `temp_div`, passo 3 de 11 (contínua 51) e contínua 38 |
| Neutro (anos normais) | `#9a9184` | 3,11:1 | `#6e675d` | 3,39:1 | cinza quente do projeto |
| Texto | `#1f1b16` | 17,12:1 | `#f2eee8` | 16,37:1 | quase preto e quase branco quentes |
| Texto secundário | `#4d473f` | 9,18:1 | `#cec7bc` | 11,28:1 | eixos e legendas |
| Texto discreto | `#6b6359` | 5,91:1 | `#a39b8f` | 6,89:1 | rodapé, fontes e linha do zero |

![Amostra da paleta nos dois temas, com o nome, o hex, o contraste e a aparência de cada cor na deuteranopia, na protanopia e na tritanopia](img/identity_palette.png)

**Como as variantes foram escolhidas.** A primeira tentativa, com os passos mais saturados das escalas de 11 tons nos dois temas, passava nos pares exigidos, mas falhava em três outros: úmido e frio ficavam quase iguais na tritanopia (distância 2,0), úmido e neutro na protanopia (4,3), e seco e quente na deuteranopia do tema escuro (6,8). Seca e calor são classes do mesmo mart e podem aparecer juntas num gráfico do dashboard, então a escolha final saiu de uma busca exaustiva ao longo das escalas oficiais. Entre as combinações com pelo menos 3:1 de contraste no fundo, ficou a que maximiza a menor distância entre todos os pares de cores de dados, com e sem simulação; no escuro, entre as que passam em todos os pares, a que mais separa seco de neutro, o par do gráfico principal. O seco e o quente se diferenciam pelo eixo vermelho-verde, justamente o que a protanopia e a deuteranopia perdem, então só a claridade os separa. Por isso o quente do tema claro é o extremo da escala (#67001f, bem mais escuro que o seco) e o do escuro é um salmão claro (#de8475). O neutro é um cinza quente próprio, porque o centro das escalas do IPCC é quase branco: é o tom mais discreto que ainda tem 3:1 de contraste.

**Sem cor de destaque.** Uma versão anterior tinha um roxo para os títulos, escolhido por ficar longe das cores de dados. Ele foi descartado: era a única cor sem função no contexto do projeto e destoava da paleta terrosa. A paleta fica restrita a cores com função, as que codificam uma classe climática e as de texto. O título usa a cor principal do texto de cada tema, e o destaque visual fica só com os dados (o marrom da seca) e com o peso da fonte (o 73% em negrito no subtítulo).

**Validação.** O contraste segue a fórmula de luminância relativa do WCAG 2.x: 4,5:1 para texto, 3:1 para as cores de dados (critério 1.4.11, objetos gráficos). A grade é decorativa e fica de fora. O daltonismo é simulado com a biblioteca daltonlens (0.1.5), usando o modelo de Viénot (1999) para protanopia e deuteranopia e o de Brettel (1997) para tritanopia, com severidade total, como a própria biblioteca recomenda. A distância entre duas cores é medida em CAM02-UCS com a colorspacious (1.1.2), um espaço feito para que distâncias iguais pareçam diferenças iguais. O limiar do projeto é de 15 unidades, com visão normal e em cada simulação, para todos os pares de cores de dados. Diferenças de poucas unidades já se percebem lado a lado em áreas grandes, e a folga é para marcas pequenas, como os pontos de 2 a 3 px do gráfico do README. Os pares exigidos ficaram assim: seco contra neutro com 23,0 no tema claro e 16,9 no escuro; quente contra frio com 48,2 e 30,3. O pior par de todos é seco contra quente no tema escuro, com 15,8 na tritanopia. O script `scripts/check_visual_identity.py` refaz todas as medidas, falha se algum limite for violado e gera a amostra acima e a simulação do gráfico do README (`docs/img/identity_cvd_chart.png`); um teste do pytest roda a mesma verificação no CI. A simulação é um modelo de dicromacia completa, e cada pessoa tem um grau próprio, por isso a regra de uso abaixo de nunca depender só da cor.

**Tipografia.** A fonte é a [IBM Plex Sans](https://github.com/IBM/plex) (IBM, versão 3.005, licença SIL Open Font License 1.1), nos arquivos estáticos regular e negrito publicados pela própria IBM no repositório oficial. A escolha saiu da comparação de três fontes abertas, todas em versões estáticas (um arquivo por peso) obtidas nos repositórios dos autores: Source Sans 3 (Adobe, `adobe-fonts/source-sans`), IBM Plex Sans (`IBM/plex`) e Inter (`rsms/inter`). As três têm todos os caracteres usados nos gráficos (acentos do português, sinal de menos, ≤, ×, ° e travessão), o zero sem traço, e o matplotlib seleciona corretamente o arquivo negrito de cada uma quando os dois pesos são registrados. A Plex é a que melhor separa os caracteres que se confundem em tamanho pequeno: o I maiúsculo tem barras em cima e embaixo e o l minúsculo tem cauda, enquanto na Inter o I e o l são idênticos. Ela também tem altura do x de 0,516 em, contra 0,486 na Source Sans 3, então o texto pequeno fica maior na mesma medida em pontos. A Inter tem a maior altura do x (0,546 em), mas é a mais larga e repete a ambiguidade do I e do l. Os arquivos ficam versionados em `src/atlas_da_lavoura/viz/fonts/`, com a licença, e são registrados no matplotlib quando o gráfico é gerado, então ele sai igual em qualquer máquina e no CI, sem instalar fonte no sistema. Alternativas descartadas: a Atkinson Hyperlegible (Braille Institute), usada numa primeira versão, distingue bem os caracteres, mas o zero com traço interno deixava anos e percentuais com aparência de defeito ("2ØØ5", "−2Ø"); Arial e Frutiger, recomendadas pelo IPCC, são proprietárias; as versões variáveis das três candidatas, as únicas no Google Fonts, não servem porque o matplotlib usa só a instância padrão e não seleciona o negrito; a DejaVu Sans, padrão do matplotlib, é larga e não distingue I de l.

**Fundos do site (fase 12).** Os gráficos do README continuam sobre os fundos do GitHub (#ffffff e #0d1117). O site usa um branco quente, `#fcfbf9`, tirado do rascunho aprovado, e uma faixa de destaque com fundo próprio, `#efebe2`, para a busca de município. No tema escuro, o fundo é um quase preto quente, `#13110e`, com luminância próxima da do `#0d1117`, para as variantes escuras das cores manterem o contraste já validado; a faixa escura é `#1f1b16`. Os dois fundos entram em `identity.py` (`SITE_BACKGROUND` e `BAND`) e no checker: o texto precisa de 4,5:1 sobre os dois, e os dados e o extremo forte da rampa do mapa, de 3:1 sobre o fundo da página. No claro, o par mais justo é o cinza neutro das barras sobre o branco quente, com 3,01:1, e no texto o "texto discreto" sobre a faixa, com 4,97:1. No escuro, o mais justo é o marrom da seca sobre o fundo, com 4,24:1; esse marrom só aparece em marcas gráficas e no número grande, nunca em texto pequeno. Um teste confirma que o checker acusa uma faixa sem contraste. Alternativa descartada: manter o branco puro, que era a referência do GitHub, não a do produto.

**Três vozes da mesma família (fase 12).** O site usa três famílias da IBM Plex, cada uma com uma função:
- a Plex Serif, no peso Regular, nos títulos e no parágrafo de abertura, que faz parte da manchete;
- a Plex Sans no texto corrido e na interface;
- a Plex Mono nos números, rótulos e metadados (faixa superior, eixos, números de apoio, tabelas e números no meio das frases).

A única exceção é o número de destaque da página (o 73% da Análise), em Plex Sans Bold, mais pesado que qualquer peso da Mono, como no rascunho aprovado. A identidade declara essa exceção em `DISPLAY_NUMBER`. As três famílias são da mesma superfamília e foram desenhadas juntas, então combinam sem disputar atenção, e a separação deixa claro o que é manchete, o que é texto e o que é dado. Os arquivos vêm dos releases oficiais da IBM (`@ibm/plex-serif@2.0.0`, fonte 3.006, e `@ibm/plex-mono@2.5.0`, fonte 2.005, com a mesma licença OFL da Sans) e entram só nos pesos usados: Serif Regular, Mono Regular e Mono SemiBold, além da Sans Regular e Bold. No repositório ficam os TTF, para o matplotlib, e no site os subsets Latin1 em woff2 (23, 18 e 18 KB). A Serif começou em SemiBold e passou para a Regular na comparação com o rascunho aprovado, em que os títulos são leves e grandes; continua sendo um peso só. A validação da Plex Sans virou automática para as cinco fontes, em `scripts/check_visual_identity.py`: nome da família, licença, todos os caracteres usados pelo projeto, zero sem traço nem ponto, I, l e 1 com contornos diferentes, altura do x de pelo menos 0,5 em (Sans 0,516, Serif 0,516, Mono 0,516) e o matplotlib escolhendo o arquivo certo para cada peso; o checker também exige que o peso do número de destaque exista entre os arquivos da Sans. Ela achou o único problema: o zero padrão da Plex Mono tem um ponto no meio. Isso deixaria anos e percentuais com a mesma aparência de defeito que eliminou a Atkinson Hyperlegible. O conjunto estilístico `ss04` da própria fonte troca esse zero pelo zero liso da Sans e da Serif (o recurso `zero` faria o oposto, cortando o zero) e não altera nenhum outro caractere. Por isso a identidade declara `ss04` como recurso sempre ligado na Mono, e o CSS gerado o aplica. Um teste confirma que o checker acusa o zero com ponto quando o `ss04` é retirado. Os `@font-face`, as pilhas de fontes e a escala de tamanhos do site (com `clamp()` entre 360 e 1.240 px de largura) são gerados de `identity.py` por `scripts/make_web_tokens.py`, com teste de drift. Alternativas descartadas: usar só a Sans com pesos diferentes, que não distingue o dado do texto; e uma serifa ou monoespaçada de outra família, que exigiria nova validação de legibilidade e criaria contraste de desenho sem função.

**Uma fonte única para a identidade.** Cores (com papel, variantes e origem), tipografia, escala de tamanhos e o estilo do matplotlib ficam em `src/atlas_da_lavoura/viz/identity.py`. O estilo é gerado a partir das cores (`rc_params`, `apply_style`), e `as_dict()` exporta tudo num dicionário serializável em JSON, base para gerar o tema do Power BI. Alternativa descartada: arquivos `.mplstyle` com as cores escritas à mão, que repetiriam a paleta e deixariam o tema do Power BI sem uma origem comum. A fonte do dashboard será revista na fase do Power BI, porque o serviço tem a sua própria lista de fontes.

**Desvios deliberados do guia do IPCC.** O título do gráfico do README é em negrito, embora o guia peça para evitar negrito: ali o gráfico funciona como manchete, não como figura de relatório. Os eixos não são pretos no tema escuro, onde preto não teria contraste. O neutro não vem das escalas do IPCC.

**Regras de uso.** O seco é a cor da seca e de nada mais, e os anos normais são sempre o neutro. Cada gráfico destaca uma classe de cada vez contra o neutro; quando duas classes aparecem juntas, a diferença também vem da legenda, de rótulos diretos ou da posição, nunca só da cor.

## BigQuery em produção: sandbox e arquitetura enxuta

**O que roda onde.** O PostgreSQL local continua sendo o ambiente de desenvolvimento e o banco do CI, e é o único que guarda o clima diário (93,6 milhões de linhas). O BigQuery é o warehouse de produção: projeto `atlas-da-lavoura`, região `southamerica-east1`, no modo sandbox. Ele recebe a PAM, as Localidades, o IPCA, o mapa de células e os indicadores climáticos por janela já calculados no Postgres, e o dbt constrói ali todos os modelos a partir deles. O produto não lê o warehouse: o site vai ler arquivos pequenos e pré-agregados, gerados pela camada de servir dados e publicados numa CDN. Por isso o warehouse pode ficar vazio ou expirar sem que nada saia do ar, e ele só precisa existir no momento de publicar dados novos.

**Por que o clima diário não sobe.** O clima diário tem cerca de 4,5 GB lógicos, e a única etapa que o lê é o cálculo dos indicadores por janela (`int_climate__window_indicators`). Esse cálculo roda uma vez no Postgres, e só o resultado, com 350 mil linhas e 67 MiB, sobe para o BigQuery como uma fonte derivada. Os outros modelos do clima (normais, fato de clima, associação com o rendimento) são construídos no BigQuery a partir dela.

**Limites do sandbox.** Conforme a [documentação oficial](https://docs.cloud.google.com/bigquery/docs/sandbox), consultada em 2026-11-06:
- **Armazenamento:** limite vitalício de 10 GiB, e a cota não é devolvida quando os dados são apagados. Cada carga e cada reconstrução de tabela consomem cota de forma cumulativa, por isso o desenvolvimento e os testes ficam no Postgres, e o BigQuery recebe carga e build só quando há dados novos a publicar.
- **Consultas:** 1 TiB processado por mês. Um build completo lê poucos GB.
- **Expiração:** tabelas, views e partições expiram em 60 dias.
- **Proibido:** DML (INSERT, UPDATE, DELETE, MERGE), streaming e Data Transfer Service.

O que o projeto precisa foi testado na prática, num dataset descartável: load job de Parquet com substituição da tabela, `create or replace table … as select`, `create or replace view` e `alter table … set options` funcionam; INSERT e DELETE são recusados. O dbt-bigquery cria tabelas, views e seeds exatamente com essas operações, e o projeto só usa materializações `table` e `view`, sem `incremental` nem `snapshot`.

**O dbt igual nos dois bancos.** A macro `use_derived_climate_source()` (em `dbt/macros/warehouse_layout.sql`) é verdadeira no BigQuery e falsa no Postgres. Quando verdadeira, `int_climate__window_indicators` vira uma view sobre a fonte `raw.climate_window_indicators`, com as mesmas colunas e tipos, e o modelo e a fonte do clima diário e o teste de virada de ano, que leem o dado diário, ficam desligados. Todo o resto do projeto continua fazendo `ref` do mesmo modelo e não muda. A macro também lê uma variável, para que o mesmo caminho rode no Postgres: o CI exporta os indicadores, carrega a fonte derivada e reconstrói o projeto nesse modo, com todos os testes. Alternativas descartadas: manter modelos separados para produção duplicaria regras e testes; fazer cada modelo seguinte escolher entre `ref` e `source` espalharia a condição; materializar a fonte derivada como tabela no BigQuery gastaria 67 MiB de cota a cada build sem ganho, porque a view só repassa a tabela raw.

**A raw no BigQuery.** Sem DML, cada fonte vira uma tabela substituída inteira por um único load job (`WRITE_TRUNCATE`), o que é atômico: uma falha no meio deixa a versão anterior. Os nomes de coluna com hífen recebem `_`, a mesma troca que a macro `source_column` faz no SQL. A coluna `_source_url` é a mesma URL em todas as linhas de um arquivo e respondia por 39% do tamanho da PAM, então no BigQuery ela fica uma vez por arquivo na tabela de controle `raw._load_manifest`, junto com a data de ingestão e o número de linhas. Ficam em cada linha só os metadados que o staging lê (`_ingested_at` e `_loaded_at`), e com isso o dbt é o mesmo nos dois bancos. A carga compara a data de ingestão de cada arquivo com o manifesto e só recarrega uma tabela quando algum arquivo mudou ou quando a tabela não existe mais (expirou). O Postgres mantém o desenho atual de propósito: lá a carga substitui um arquivo de cada vez e usa `_source_file` em cada linha para apagar e recarregar só aquela partição da PAM e para detectar dados de arquivos removidos; o Postgres não tem cota vitalícia, e os 470 MB a mais no disco local não pesam. A diferença fica restrita aos metadados de carga, que nenhum modelo lê.

**Razões, logaritmos e exponenciais em ponto flutuante.** O primeiro build real no BigQuery falhou em dois testes que passam no Postgres: as participações por território não somavam 1 e a decomposição área × rendimento não fechava, ambas com tolerância de 1e-9. No BigQuery, a divisão entre dois NUMERIC devolve um NUMERIC arredondado a 9 casas decimais, e `LN` e `EXP` de um NUMERIC também; no Postgres o `numeric` guarda cerca de 20 dígitos. Somadas sobre centenas de regiões, as participações arredondadas chegavam a 3e-7 de erro. A regra adotada vale para os dois bancos: razões, logaritmos e exponenciais são calculados em ponto flutuante (macro `as_float()`), e o NUMERIC fica para as quantidades medidas (toneladas, hectares, valor nominal). Isso alcançou os rendimentos, as participações, o HHI, a decomposição, a bienalidade do café, a tendência log-linear, o índice encadeado do IPCA e as taxas de acerto. No Postgres, a comparação de todas as tabelas antes e depois da mudança mostrou só diferenças no último dígito, e nenhuma coluna de texto, inteira ou booleana mudou, então as classes e os resultados publicados são os mesmos. Alternativa descartada: afrouxar a tolerância dos testes só no BigQuery esconderia a perda de precisão em vez de removê-la.

**Trava de segurança.** Toda escrita no BigQuery passa por uma confirmação explícita. O `load-raw --target bigquery` e o `bq-dbt build` mostram antes a estimativa do que vão gravar, em bytes lógicos pelas regras do BigQuery, ao lado do que o registro de cota diz que já foi usado. Só escrevem depois de um "yes" digitado ou da flag `--yes`. No dbt, um hook `on-run-start` recusa `run`, `build`, `seed` e `snapshot` num target BigQuery que não venha do `bq-dbt`; o dbt cria os datasets vazios antes do hook, o que não ocupa armazenamento. Depois de cada escrita, o tamanho lógico do que foi gravado é medido e acrescentado a `docs/bigquery_quota_log.csv`. Essa é a melhor medida disponível, porque o consumo da cota em si não é exposto.

**Validação.** O primeiro ciclo foi feito com tabelas vazias: `load-raw --empty` e `bq-dbt build --empty` rodaram todo o SQL do projeto no BigQuery a custo zero de cota e acharam um erro de dialeto (um teste com `WHERE` sem `FROM`, que o Postgres aceita e o BigQuery não), corrigido com uma subconsulta de uma linha. Antes disso, o desenho do BigQuery foi montado num Postgres descartável com os dados completos, sem clima diário e com a fonte derivada: todos os testes passaram, e as tabelas ficaram idênticas às do banco de desenvolvimento, com diferenças só no último dígito de ponto flutuante. Depois do ciclo real, o script `scripts/compare_postgres_bigquery.py` comparou os dois bancos tabela a tabela, pela chave de cada uma: as 18 tabelas e views de modelos e os 7 seeds têm as mesmas contagens; produção e área são idênticas, inclusive nos totais do Brasil dos 184 pares de cultura e ano; texto, inteiros e booleanos, incluindo todas as classes de seca, calor e geada, são idênticos; os números de ponto flutuante diferem no máximo 7e-10 relativo, nas anomalias de rendimento perto de zero (rendimento ÷ tendência − 1), onde a diferença absoluta é da ordem de 1e-15. Todos os testes do dbt passam no BigQuery, com os mesmos três avisos esperados do Postgres.

## Operação do BigQuery: recarga e consumo de cota

**Quando operar.** Só quando há dados novos a publicar: o ano novo da PAM (setembro), uma atualização do IPCA que se queira publicar, uma versão nova do BR-DWGD ou uma mudança de modelo que altere resultados. Fora disso, o BigQuery fica como está e as tabelas expiram em 60 dias sem afetar o produto.

**Procedimento de recarga.** Do diretório raiz do repositório, com o Postgres local atualizado:
1. Atualizar e validar no Postgres: as ingestões necessárias, `uv run load-raw` e `dbt build`, com todos os testes passando.
2. Exportar os indicadores de janela: `uv run export-window-indicators`.
3. Carregar a raw: `uv run load-raw --target bigquery`. Ele recarrega só as tabelas com arquivo novo ou que expiraram, e mostra a estimativa antes de pedir a confirmação.
4. Se o SQL mudou desde o último ciclo, validar antes sem gastar cota: `uv run bq-dbt build --empty --resource-type model seed`, seguido de `uv run bq-dbt test`. O `--empty` substitui as tabelas por versões vazias, então ele só vale quando o build real vem logo a seguir.
5. Construir os modelos: `uv run bq-dbt build`, ou só os modelos afetados com `--select`, para economizar cota.
6. Validar contra o Postgres: `uv run python scripts/compare_postgres_bigquery.py`.
7. Rodar todos os testes no BigQuery: `uv run bq-dbt test`. O resumo desta execução vai para o `method.json` do site, então ela precisa ser completa e a última antes da exportação.
8. Exportar os arquivos do site: `uv run export-serving --target bigquery --dry-run` mostra os bytes que cada consulta vai processar (cota mensal de consulta, não de armazenamento), e `uv run export-serving --target bigquery` grava `dist/site-data/<versão>/`. Para conferir, exportar também do Postgres (`--target postgres --out dist/site-data-postgres`) e comparar com `uv run python scripts/compare_serving_bundles.py`.
9. Empacotar: `uv run package-serving dist/site-data/<versão>` gera o pacote, as notas do release e o ponteiro `data-release.json`. O release `data-v<versão>` é criado à mão com o comando que ele imprime, depois de revisar, e o ponteiro vai para a `main` num PR.
10. Atualizar a tabela abaixo a partir de `docs/bigquery_quota_log.csv`.

Num Postgres, reconstruir uma tabela sozinha (`dbt build --select <tabela>`) apaga as views que dependem dela, porque o dbt-postgres troca a tabela e remove a anterior com `drop ... cascade`. Reconstruir junto os dependentes (`--select <tabela>+` ou o build completo). O BigQuery não tem esse problema: `create or replace table` mantém as views.

Quando as tabelas expiram, o manifesto expira junto, e a próxima carga recarrega tudo: o procedimento é o mesmo, e custa um ciclo completo.

**Consumo da cota vitalícia** (10.240 MiB por projeto GCP). A cota é do projeto: quando o projeto foi recriado com o nome Atlas da Lavoura, em 2026-11-09, o registro (`docs/bigquery_quota_log.csv`) recomeçou do zero.

| Data | Operação | Gravado | Acumulado | Restante |
|---|---|---|---|---|
| 2026-11-09 | Validação com tabelas vazias: carga e build | 0 MiB | 0 MiB | 10.240 MiB |
| 2026-11-09 | Carga completa da raw | 816,8 MiB | 816,8 MiB | 9.423,2 MiB |
| 2026-11-09 | `dbt build` completo | 360,6 MiB | 1.177,4 MiB | 9.062,6 MiB |

Os ciclos do projeto GCP anterior, de 2026-11-06 a 2026-11-08, gravaram 1.350,8 MiB:
- a validação com tabelas vazias, a custo zero;
- a carga completa da raw, 816,8 MiB;
- o `dbt build` completo, 369,3 MiB;
- o rebuild de 10 modelos com as razões em ponto flutuante, 163,8 MiB;
- a camada de servir, 1,0 MiB.

O projeto anterior é encerrado depois da migração, e o consumo dele não conta para a cota do atual.

Um ciclo completo (carga e build) grava cerca de 1.180 MiB, então a cota restante comporta cerca de 7 ciclos completos, ou cerca de 25 builds sem recarga da raw. As views da camada de servir não gravam nada; cada exportação só usa cota de consulta (cerca de 440 MiB processados, 0,04% da cota mensal de 1 TiB, que se renova). A carga da PAM, com 749 MiB, é a maior parte de cada ciclo, e só se repete quando a PAM muda ou quando as tabelas expiram.

## Camada de servir dados: arquivos estáticos para o site

**O que é.** O site não consulta o warehouse: ele lê arquivos JSON pequenos e pré-agregados e uma malha em TopoJSON, publicados numa CDN. Os arquivos saem de views `serve_*` (schema `serve`), que leem só marts, dimensões e, na validação, os seeds de referência externa. O comando `export-serving` lê cada view uma única vez, monta os arquivos, simplifica a malha, valida tudo contra os JSON Schemas e as regras de validade, concilia os arquivos com os marts por consultas independentes e só então grava a pasta da versão, com um manifesto. O contrato dos arquivos está em [CONTRATO_DE_DADOS.md](CONTRATO_DE_DADOS.md).

**Views, não tabelas.** No BigQuery, uma view não ocupa a cota vitalícia de armazenamento; o custo passa para a consulta, no momento da exportação. O dry run das consultas da exportação, com a dimensão de municípios recalculada (um limite superior), deu cerca de 510 MiB processados, 0,05% da cota mensal de 1 TiB. Por isso o exportador lê cada view uma vez e reparte os arquivos em Python: uma consulta por município varreria as mesmas tabelas 5.571 vezes. As views expiram com o resto do sandbox, mas a exportação acontece logo depois do build, e o retrato que vale fica nos arquivos. Alternativa descartada: materializar como tabelas, o que gastaria cota a cada build sem ganho.

**Arredondamento nas views.** Cada valor publicado é arredondado no dbt, com casas fixas por tipo: inteiros para toneladas, hectares, kg/ha e mil reais; 4 casas nas frações (participações, anomalias, taxas); 2 nos z-scores; 1 nos percentuais. A macro `round_to` passa o valor por NUMERIC antes de arredondar, para que os dois bancos arredondem o mesmo decimal (o Postgres não tem `round` de ponto flutuante com casas, e o `ROUND` do BigQuery arredondaria o valor binário). O exportador recusa qualquer número de ponto flutuante que chegue sem arredondar. Com isso, os arquivos gerados do Postgres e do BigQuery são iguais, e menores.

**JSON em colunas, comprimido pela CDN.** As tabelas são objetos de arrays de mesmo tamanho, e as matrizes do mapa têm uma linha por município, na ordem do índice. Medido na matriz de produção da soja (5.571 municípios × 52 anos): 188 KiB com gzip em JSON por município, 221 KiB em JSON por ano e 345 KiB em Parquet com zstd, que ainda exigiria uma biblioteca de leitura no navegador. Arredondar a 3 algarismos significativos reduziria só 10% e perderia a exatidão. Alternativas descartadas: Parquet e Arrow (maiores aqui e com dependência no site), arredondamento para o mapa.

**Divisão dos arquivos.**
- **Base:** `catalog.json` (versão, séries, parâmetros, atribuição das fontes), o índice de municípios, `analysis.json` e `method.json`.
- **Explorar:** 24 matrizes, uma por série e medida.
- **Fichas territoriais:** Brasil, 5 macrorregiões, 27 UFs e 510 regiões imediatas. Cada arquivo de região imediata traz todos os seus municípios, com séries e rankings, o agregado da região e o risco de seca.

Por que o pacote por região imediata:
- comparado com um arquivo por município, são 510 arquivos em vez de 5.571, e os vizinhos da comparação chegam na mesma requisição;
- um pacote por UF seria grande demais: o de Minas Gerais teria cerca de 500 KiB.

Tamanhos medidos com gzip:
- **Na abertura de cada página:** Análise 36 KiB, Explorar 481 KiB (malha nacional mais a produção da soja), Município 82 KiB na mediana e Método 10 KiB.
- **Orçamento da página Município:** 100 KB. Ele é estourado nas regiões com mais de 40 municípios, com até 124 KiB. Se isso pesar na prática, a alavanca é separar um arquivo por município.
- **Pacote inteiro:** 601 arquivos, 63 MiB sem compressão e 10 MiB com gzip.

**A malha.** A malha municipal do IBGE em qualidade máxima tem 3 milhões de vértices e uma única inconsistência entre vizinhos: uma sobreposição de cerca de 1.200 m² entre Fortaleza e Caucaia. Ela fica com o município de menor código, e qualquer outro problema de cobertura interrompe a exportação.

Os passos da simplificação:
1. **Simplificação da cobertura:** `shapely.coverage_simplify`, Visvalingam–Whyatt aplicado uma vez a cada fronteira compartilhada, então os dois vizinhos recebem a mesma fronteira.
2. **Snap rounding:** a cobertura inteira é arredondada para a grade inteira do TopoJSON de uma vez, com as faces reconstruídas e cada face atribuída ao município com que mais se sobrepõe. Arredondar vértice a vértice deixava 25 municípios inválidos na malha nacional, onde duas partes da mesma fronteira ficam a menos de uma célula. Consertar cada polígono com `make_valid` quebrava a fronteira com o vizinho.
3. **Codificação:** um encoder de TopoJSON próprio guarda cada arco compartilhado uma vez e grava os anéis externos no sentido horário, como o d3-geo espera. Os testes decodificam a saída e conferem a cobertura, a contagem e os ids.

Os níveis da malha:

| Nível | Tolerância | Grade | gzip | Erro de área por município |
|---|---|---|---|---|
| Nacional | 0,025° | 10.000 | 290 KiB | mediana 1,4% |
| Contorno das UFs | 0,04° | 10.000 | 13 KiB | — |
| Uma malha por UF, para o zoom | 0,005° | 100.000 | 1,1 MiB no total, a maior de 151 KiB (MG) | mediana 0,1% |

O erro de área da malha nacional chega a 18% no 1% de municípios mais distorcidos; são os minúsculos, que ocupam poucos pixels no mapa do Brasil. A tolerância de 0,02° custaria 19 KiB a mais e passaria do orçamento da página Explorar.

Alternativas descartadas:
- mapshaper, que traria o Node para o pipeline;
- tiles vetoriais com MapLibre, exagero para 5.571 polígonos sem mapa de fundo;
- GeoJSON, que tem o dobro do tamanho.

**Café cortado em 2002 também nas participações e no HHI.** O corte das séries do café na quebra de unidade da PAM vale para toda a camada de servir, inclusive para medidas sem unidade, como participações e concentração. O motivo de substância: a relação entre o café em coco e o beneficiado varia entre regiões, conforme o tipo de café e o preparo, então até a participação de cada território mudaria artificialmente na quebra. Uma regra só, aplicada pela série publicada (`coffee_in_husk` até 2001, `coffee_processed` desde 2002), é também uma regra fácil de testar em todos os modelos e arquivos.

**Uma lógica para os testes e para o site.** Os testes de validação externa contra o IBGE e a Conab passaram a ler as views `serve_validation_*`, as mesmas que alimentam a página Método. O que o site mostra como "validado" é exatamente o que os testes conferem. O gráfico do README também passou a ler `serve_analysis_headline`, e os números do achado têm uma fonte só.

**Publicação: release do GitHub e um ponteiro no repositório.** O CI não tem acesso ao BigQuery, então os arquivos de produção saem do BigQuery no evento de publicação. O mesmo código exporta do Postgres, no desenvolvimento, no CI com a amostra e na comparação com o BigQuery.

Como a versão chega ao site:
1. O pacote de uma versão vai como asset de um release `data-vAAAA.MM.DD`: um `.tar.gz` reprodutível de cerca de 10 MiB, mais o manifesto.
2. O repositório versiona só o ponteiro `data-release.json`, com a tag, a URL, o sha256 e as versões dos esquemas.
3. O build do site baixa o pacote dessa versão, confere o sha256 e o publica em `/data/<versão>/`. Assim, cada commit do site reproduz exatamente os dados que usou.

Alternativas descartadas:
- **Versionar os arquivos no Git:** cerca de 63 MB sem compressão por versão, quase tudo reescrito a cada atualização da PAM, com diffs ilegíveis.
- **Git LFS:** a cota grátis de banda, de 1 GiB por mês, acabaria com os downloads do CI.
- **Gerar no deploy:** o CI não acessa o BigQuery, e no Postgres do CI só existe a amostra.


## Produto web: fundação (fase 12)

**Framework: Astro com ilhas React.** As páginas editoriais (Análise, Método) saem como
HTML puro, com zero JavaScript, e a interatividade pesada (mapa do Explorar, ficha do
município) entra como ilhas React que compartilham um único runtime (~69 KB gzip,
medido). Alternativas descartadas: Next.js com exportação estática (174 KB gzip de
JavaScript de base medidos num "hello world", e rotas dinâmicas exigem
`generateStaticParams` com os 5.571 municípios) e React + Vite puro (69 KB de runtime
também nas páginas de texto, que chegariam vazias antes da hidratação). O
`@astrojs/react` está fixado em 7.1.4: a 7.1.6 importa um módulo que não existe no
astro 7.4.

**Mapa: canvas 2D com d3-geo (decidido; implementação na próxima etapa).** O stack
d3-geo + topojson-client + d3-zoom + d3-selection + d3-delaunay mede ~42 KB gzip, contra
~312 KB do MapLibre e ~224–263 KB do deck.gl, e é o único com projeção cônica de
primeira classe, o padrão editorial para o Brasil. SVG puro (5.571 nós) foi descartado
para o scrub de 52 anos por risco de travamento no celular; uma camada DOM fina sobre o
canvas cuida de tooltip, foco e acessibilidade, e um botão "ver como tabela" oferece os
mesmos dados em tabela ordenável e navegável por teclado.

**Identidade no site: tokens gerados, não copiados.** `web/src/styles/tokens.css` e
`web/src/lib/tokens.ts` são gerados de `identity.as_dict()` por
`scripts/make_web_tokens.py` e commitados, para o build do site não depender de Python;
um teste no pytest falha quando eles divergem da identidade. A escala do tipo vira rem
preservando as razões (12 pt = 1 rem). A identidade ganhou uma escala sequencial para o
coropleto, na família do cinza quente neutro (marrom significa seco e verde-azulado
significa úmido, então nenhum dos dois pode codificar intensidade): 6 passos uniformes
em CAM02-UCS, do bege claro ao quase preto no tema claro e o inverso no escuro,
validados no checker (luminância monotônica, extremos ≥ 4,5:1, extremo forte ≥ 3:1
contra o fundo e ΔE ≥ 15 entre vizinhos em cada deficiência simulada).

**Dados no build: ponteiro + sha256.** O build baixa o tarball do release fixado em
`data-release.json`, confere o sha256 e o tamanho e extrai para `public/data/<versão>/`;
o tarball verificado fica num cache com chave pelo próprio sha256. Os tipos TypeScript
são gerados dos JSON Schemas do contrato (json-schema-to-typescript) e uma validação de
fumaça com ajv (draft 2020-12) confere um arquivo de cada esquema e as versões contra o
ponteiro. Nada disso é commitado: os tipos não podem divergir dos schemas.

**CI do site:** workflow próprio (`site.yml`) que roda em todo pull request, com o filtro
de caminho dentro do workflow: um job `changes` detecta se `web/**`, o ponteiro de dados
ou o próprio workflow mudaram, o job pesado `site` só roda nesse caso, e um agregador
`site-status` sempre reporta — passa quando o `site` passou ou foi pulado pelo filtro e
falha quando ele falhou. É o `site-status` que entra como required check na regra da
`main`; um required check com filtro de caminho no gatilho ficaria "Pending" num PR que
não toca o site e travaria o merge. Gates do job `site`: astro check, Vitest, build,
Playwright + axe (zero violações WCAG 2.x A/AA, temas claro e escuro) e Lighthouse CI com
orçamento por página: desktop com erro abaixo de 0,90 em todas; no celular, erro abaixo
de 0,90 (Análise, Municípios e Método) e aviso abaixo de 0,80 no Explorar. O
`astro preview` do Astro 7 vira daemon e não serve para o `webServer` do Playwright; os
testes usam um servidor estático comum.

**CI do site: navegador sem `--with-deps` e timeouts explícitos.** O job instala só o
Chromium headless shell (`playwright install --only-shell chromium`), sem o
`--with-deps` do exemplo da documentação do Playwright. O `--with-deps` roda `apt-get`
contra os espelhos do Ubuntu: na primeira execução do PR, uma falha de DNS desses
espelhos deixou o job 10 minutos parado tentando instalar fontes de fallback (chinês,
japonês, tailandês) que o site não usa, enquanto todas as bibliotecas do Chromium já
vinham na imagem `ubuntu-24.04`. Se uma imagem futura não tiver alguma, o navegador
falha ao abrir, em segundos, dizendo qual falta. O Lighthouse CI usa o Google Chrome da
própria imagem. O cache dos navegadores foi descartado porque a documentação do
Playwright não o recomenda: restaurar leva quase o mesmo tempo que baixar. Quanto aos
limites de tempo: o padrão do GitHub é 360 minutos por job, então cada passo de rede ou
de navegador ganhou o seu próprio `timeout-minutes` (de 3 a 6 minutos), e o job tem um
teto de 15. A restauração dos caches desiste de um segmento travado em 2 minutos, em vez
de 10, e segue como cache miss. O download do pacote de dados aborta em 2 minutos. No
CI, o Playwright roda com um worker e tem `globalTimeout` de 4 minutos, abaixo do limite
do passo, para parar sozinho e ainda imprimir o relatório.

**Dependências do site: Dependabot e vulnerabilidades atuais.** O Dependabot também
acompanha o ecossistema npm de `web/`, semanalmente, com o mesmo prefixo de commit das
actions. As vulnerabilidades que o `npm audit` acusa hoje (9 "high") estão todas na
cadeia `basic-ftp`/`proxy-agent` dentro do Lighthouse/puppeteer — ferramentas que só
rodam no CI e na máquina de desenvolvimento. Nada disso entra no site publicado, que é
HTML estático sem dependência de runtime além das ilhas React empacotadas no build;
`npm audit fix --force` rebaixaria o Lighthouse CI e foi descartado.

**TypeScript fica na versão 6 (decisão de 2026-11-11).** O TypeScript 7 é o port nativo
do compilador para Go e saiu sem a API programática que as ferramentas de checagem de
tipos de frameworks usam; o próprio anúncio da versão diz que projetos com Vue, MDX,
Astro e Svelte precisam continuar no TypeScript 6 por enquanto, e que a API nova deve
chegar na 7.1. No projeto, o `@astrojs/check` (que roda o `astro check` do CI) aceita só
`typescript` 5 ou 6, e o `@volar/kit`, base do servidor de linguagem do Astro, declara
`typescript <7`; com o TypeScript 7, o `npm ci` nem resolve as dependências. Forçar a
instalação com `--legacy-peer-deps` foi testado e descartado: o próprio `astro check`
recusa o 7.0 ("does not currently support TypeScript 7.0") e manda instalar o 6. O PR
do Dependabot que subia para a 7 (#15) foi fechado sem merge, e o Dependabot passou a
ignorar as versões principais do `typescript` em `web/`; as correções e versões menores
do 6 continuam chegando. O caminho do Astro para o TypeScript 7 é o
`@astrojs/ts-content-mapper`, que faz o `tsc` checar os arquivos `.astro` direto, mas ele
está na versão 0.2.0, é experimental e exige o TypeScript 7.1, que hoje só existe em
beta; o Astro avisa que o `astro check` será descontinuado numa versão futura. Reavaliar
quando o TypeScript 7.1 for estável e o `@astrojs/ts-content-mapper` deixar de ser
experimental: aí a checagem migra para ele e a regra sai do `.github/dependabot.yml`.

**Hospedagem (decidido; configuração na etapa de publicação):** o site vai para a
Cloudflare (Workers static assets), que no plano gratuito, sem cartão, serve estáticos
sem limite de banda e aceita cabeçalhos de segurança via `_headers`; o GitHub Pages não
tem cabeçalhos customizados e só permite um site por repositório, então o dbt docs
permanece nele e passará a `docs.atlasdalavoura.com.br` quando o DNS do domínio estiver
na Cloudflare (o registro.br não tem ALIAS/ANAME no apex, então os nameservers serão
delegados ao DNS gratuito da Cloudflare).

## Produto web: página Análise (fase 12, etapa 3)

**Nenhum número escrito à mão.** Todo número que o site imprime, inclusive no meio do
texto, nos rótulos dos gráficos, nas tabelas e nos nomes acessíveis das barras, vem de um
arquivo do pacote de dados e leva a sua origem na marcação: uma referência
`arquivo#/ponteiro-json|formato` (por exemplo
`analysis.json#/headline/below_trend_share_all_years|pct`), com operações explícitas
quando o número não está pronto no arquivo (`max` do último ano das séries, `count` das
diferenças documentadas, o ano entre parênteses de uma citação). As linhas de tabela
citam o número da linha e as colunas, e os ticks dos eixos são conferidos contra a faixa
da coluna desenhada (`within`) ou contra os anos que existem nela (`member`). O teste de
ponta a ponta (`web/e2e/provenance.ts`) percorre o texto visível e os atributos lidos por
leitores de tela, baixa os arquivos citados do próprio servidor, como o navegador faz, e
falha se algum número não tiver origem ou não for exatamente o que o arquivo diz. Dois
testes negativos provam que ele pega um número digitado e um número que diverge do
arquivo. A página usa o mesmo código de referência (`web/src/lib/provenance.ts`) para
gerar o texto, então o número e a origem não podem divergir. Alternativas descartadas: um
lint que proíba literais numéricos no código, que não pega um número copiado errado num
texto, e um teste de snapshot da página, que congela o valor sem provar de onde ele veio.

**Números estruturais, à parte e marcados.** A regra vale para os números de dado e não
retira elementos editoriais. A numeração de figuras, tabelas e notas ("Figura 1") e os
marcadores das listas numeradas são números estruturais: não vêm dos dados, então não
citam o pacote, mas são marcados explicitamente (`data-structural`) e seguem regras
rígidas (`web/src/lib/structural.ts`). Uma marca contém só "Figura N", "Tabela N" ou
"Nota N", com N igual à sua posição na página entre as marcas do mesmo tipo, sem elementos
dentro e sem citar dados. Uma lista numerada é um `<ol data-structural="list">` que conta a
partir de 1. Fora disso, o número é tratado como dado e precisa de referência, e número em
conteúdo gerado por CSS é sempre recusado. Um teste negativo injeta disfarces na página e
confere que todos são recusados: "Figura 88" fora da sequência, "73%" numa marca de nota,
uma frase com dados numa marca de tabela, uma lista começando em 537, uma lista numerada
sem marca e um "−9%" gerado por `::before`. A alternativa, uma lista de exceções por
seletor CSS, deixaria passar qualquer número que caísse num elemento isento.

**Gráficos em JSX, renderizados no build.** Os gráficos são componentes React com
`d3-scale` e `d3-array` (4.0.3 e 3.2.5, publicados com procedência SLSA pelo GitHub
Actions dos repositórios oficiais; conferido antes de instalar), mas são renderizados na
geração do site, sem diretiva de cliente, e a página não carrega o runtime do React. A
interatividade é pequena e vai em JavaScript próprio, embutido no HTML: o tooltip com
foco itinerante (as setas, Home e End percorrem os anos; Esc fecha; WCAG 1.4.13), a busca
de município e um script de poucas linhas que faz as barras crescerem quando entram na
tela. Com movimento reduzido, ou sem JavaScript, as barras já aparecem prontas. O SVG
desenha só barras e linhas e estica com a largura (`preserveAspectRatio="none"`, traços
que não escalam); os ticks, as anotações dos piores anos e o tooltip são HTML posicionado
em porcentagem, e por isso o texto mantém o tamanho no celular e na tela larga.
Alternativas descartadas: uma ilha React hidratada (cerca de 69 KB de runtime para um
tooltip e uma busca) e duas versões do SVG trocadas por media query, que duplicariam o
DOM e os elementos focáveis. A figura traz ainda as tabelas com todos os valores, num
`<details>`, como alternativa ao gráfico.

**Grade e rodapé.** O conteúdo usa um contêiner de 1.240 px com grade de 12 colunas. O
texto corrido fica limitado a cerca de 70 caracteres (38 rem, nas colunas centrais), e
figuras, números de destaque e, nas próximas etapas, mapas ocupam a largura toda; a faixa
superior e o cabeçalho acompanham a largura maior. O rodapé ficou enxuto: a nota de
associação, a linha curta das fontes, com o ano da citação do BR-DWGD lido do catálogo,
o link para as citações completas e a nota de projeto independente com a versão dos
dados. As citações completas, lidas do catálogo, foram para a página Método, todas com a
mesma estrutura (nome, citação, publicação, período, uso no projeto, condições de uso e
endereço). A regra 8 do contrato de dados foi atualizada para esse arranjo.

**Ajustes da revisão visual.** Todos os blocos (abertura, número de destaque, figura,
números de apoio, busca) começam na primeira linha da grade, a mesma margem do nome do
site no cabeçalho; o texto corrido continua limitado à largura de leitura. A monoespaçada
ficou só para números e rótulos curtos (rótulo da seção, faixa superior, eixos, anotações,
siglas). Legendas, subtítulos dos painéis, a linha de fonte, os links da figura, o tooltip
e os textos de apoio voltaram para a sem serifa, com os números dentro deles ainda em
monoespaçada. Os títulos usam `text-wrap: balance` (com uma largura máxima onde não há
suporte) e prendem as palavras de uma ou duas letras à seguinte com espaço inseparável
(`web/src/lib/typography.ts`), como pede a tipografia em português; um teste mede as
linhas de cada título em quatro larguras de tela, e um caso negativo confirma que ele
acusa uma palavra curta no fim da linha. O painel das UFs mostra as seis primeiras e
recolhe as demais num `details` ("Mostrar as 16 UFs", com o 16 contado no pacote), que
abre pelo teclado e funciona sem JavaScript; a tabela completa continua na figura. A
definição de célula comparada foi para um "O que é uma célula comparada?" que abre ao
clicar. Alternativa descartada para o painel: um botão com JavaScript, que deixaria as
UFs inacessíveis sem script.

**Comparação com o rascunho aprovado.** Os rascunhos de tela aprovados no planejamento
são a referência visual de cada página. A Análise segue a versão combinada; Explorar,
Município e Método seguirão as versões editoriais, com os mesmos ajustes da combinada.
Os rascunhos ficam fora do repositório, e as marcações provisórias e os números deles não
são reproduzidos. O que mudou na Análise:
- **Abertura:** no computador, o título e o parágrafo de abertura ocupam as oito colunas
  da esquerda e o número de destaque as quatro da direita, na altura do título e na
  primeira tela, sob um filete na cor da seca; no celular, a ordem continua título,
  parágrafo, número. O parágrafo encurtou para uma frase, já que o achado passou para o
  bloco do 73%, com o 43% em negrito na frase. O título vai até 3,25 rem: é o maior tamanho
  em que ele cabe em duas linhas nas oito colunas, com as palavras curtas presas.
- **Figura:** o cabeçalho ficou compacto, com "Figura 1." e o título numa linha em sem
  serifa negrito e a legenda ao lado, mais uma frase de leitura para o leitor não técnico
  ("Abaixo de zero, a safra rendeu menos que a tendência"). As barras ficaram mais largas.
  O rodapé da figura tem a fonte de um lado (a palavra "Fonte" leva às citações completas,
  como pede a regra 8 do contrato) e "Dados · Método · Link" do outro; o "Link" aponta
  para a âncora da própria figura (`#figura-1`), sem copiar nada para a área de
  transferência. Os eixos, os rótulos dos piores anos e o painel das UFs continuam, embora
  o rascunho não os tenha: sem eles o gráfico não se lê, e o painel foi pedido na etapa.
  O cinza neutro da identidade fica, porque o cinza mais claro do rascunho não tem 3:1 de
  contraste.
- **Números de apoio:** vêm logo após a figura, com o título só para leitores de tela,
  filete fino e frases curtas. A cor só aparece onde significa algo: o −9% na cor da
  seca e o 197 de 217 no verde-azulado da água. O rótulo da seção e o menu ficam na cor
  do texto, já que o marrom é só da seca.
- **Busca:** fica numa faixa de largura total com fundo próprio, em duas colunas, com
  campo sublinhado e o botão "Abrir ficha", que abre a melhor correspondência mesmo antes
  de o índice terminar de carregar. Para a faixa ocupar a largura toda sem `100vw` (que
  cria rolagem horizontal quando a barra de rolagem aparece), o `main` deixou de ser um
  contêiner: cada página envolve o próprio conteúdo.
- **Cabeçalho e rodapé:** a faixa superior separa os dados das fontes, o nome do site
  cresceu em serifa e o menu ficou em caixa alta, com sublinhado na página atual. O
  rodapé manteve o conteúdo aprovado, em duas colunas: o texto de um lado, Método e GitHub
  do outro.

**Busca e páginas de município.** A busca usa o padrão combobox da ARIA 1.2, ignora
acentos e maiúsculas e ordena primeiro os nomes que começam com o texto digitado. O
índice é o próprio `municipalities.json` do pacote, baixado só no primeiro foco do campo
(61 KiB com gzip), para a página não pagar por ele na abertura. A alternativa, gerar no
build um índice menor, criaria um segundo arquivo de dados fora do pacote versionado. A
busca leva a `/municipio/<código IBGE>/`, uma das 5.571 páginas estáticas geradas no build
a partir do índice, como a descoberta técnica previu. Elas ainda são esqueletos, com
cerca de 2,6 KB cada, e o build completo leva cerca de 10 s.

## Produto web: página Explorar, parte A (fase 12, etapa 4)

**Totais em círculos proporcionais, rendimento em coroplético.** Um coroplético pinta o
município inteiro, e o olho lê a área pintada, não o valor. Com valores absolutos, os
municípios enormes com produção média dominam o mapa, e as regiões de municípios pequenos e
muito produtivos somem: é o erro clássico do coroplético de totais. Por isso as medidas
extensivas (produção, área colhida, área plantada ou em produção e valor real) são círculos
proporcionais no ponto representativo de cada município, com a área do círculo
proporcional ao valor (o raio vai pela raiz quadrada), sobre um mapa base neutro: os
municípios com dado num tom claro, os sem dado hachurados e o contorno das UFs. Os
círculos maiores são desenhados primeiro e os menores ficam por cima, e o ponteiro pega o
círculo de cima. "Não produziu" é a ausência de círculo, e a legenda diz isso. A área
plantada entrou nos círculos, embora o pedido citasse só produção, área colhida e valor,
porque também é um total. O rendimento, uma razão (medida intensiva), continua no
coroplético: a cor de cada município é o próprio valor por hectare e não depende do
tamanho dele. Alternativas descartadas: a densidade (produção por km²), que é intensiva e
caberia num coroplético, mas responde a outra pergunta (o quanto a cultura ocupa o
território) e esconde os totais; o cartograma, que deforma a geografia que o leitor do agro
usa para se achar; e o raio proporcional ao valor, que exagera as diferenças (o dobro do
valor pareceria quatro vezes maior).

**Escala fixa dos círculos.** Há uma escala por série e medida para toda a série
temporal, como nas classes de cor: o maior valor de qualquer ano recebe o raio máximo (24
unidades do mapa nacional, que tem 1.000 de largura), e os tamanhos se comparam de um ano
para outro. A escala é em unidades do mapa, então o mesmo valor tem o mesmo tamanho no mapa
e na legenda em qualquer largura de tela (a legenda é medida em unidades do contêiner,
`cqi`, cuja largura é a do mapa), e uma UF em foco mantém o tamanho nacional. A legenda
mostra três círculos de referência em valores redondos da sequência 1-2-5, próximos do
máximo, de um quinto e de um vigésimo quinto dele (na soja, 2.000.000, 200.000 e
50.000 t). Eles são citados no pacote pela operação `circle:k`, que o teste de procedência
recalcula (`web/src/lib/symbols.ts`). Abaixo de 0,75 px, o raio fica nesse mínimo, para que
todo município que produziu apareça; aí a área deixa de ser proporcional, o que só afeta
círculos pequenos demais para comparar a olho (no celular, valores abaixo de cerca de 1% do
máximo). Alternativa descartada: uma escala por ano, que impediria comparar anos. Abaixo da
legenda, uma frase diz que a área de cada círculo é proporcional ao valor, na mesma escala
em todos os anos.

**Ponto representativo calculado na malha publicada.** O pacote de dados não traz o ponto
representativo dos municípios: o do warehouse, calculado sobre a malha completa, não sai
na camada de servir. O navegador o calcula sobre a malha publicada com o algoritmo do
`representative_point` do shapely (o InteriorPointArea do GEOS): uma linha horizontal na
altura do centro do polígono, desviada dos vértices, e o meio do trecho interno mais
largo. O ponto fica sempre dentro do polígono desenhado, ao contrário do centroide de um
município em forma de meia-lua, e também ancora o tooltip e a navegação pelo teclado.
Alternativa descartada: publicar o ponto no pacote, o que exigiria um novo ciclo de dados
no BigQuery para uma informação que a malha publicada já permite derivar.

**Classes fixas do rendimento, por quantis de todos os anos.** O rendimento tem cinco
classes, as mesmas em todos os anos, para que uma cor signifique o mesmo rendimento em
1980 e em 2025. Os limites são os quintis de todos os valores positivos da série, com
todos os anos juntos (cada classe reúne a mesma quantidade de pares município × ano),
arredondados para a sequência 1-2-5 ou, se o arredondamento juntar dois limites, para dois
ou três algarismos significativos. É o que acontece no rendimento, que varia pouco: na
soja, os limites são 1.700, 2.200, 2.700 e 3.200 kg/ha. Os zeros, os nulos e os
rendimentos de área colhida pequena demais (parágrafo seguinte) não entram no cálculo,
porque têm estados próprios. O mesmo código (`web/src/lib/classify.ts`) calcula os
limites no build, para a legenda, e no teste de procedência, que os recalcula a partir das
matrizes publicadas (`explore/soybean/production_t.json#/values!ybreak:0|int`).
Alternativas descartadas: intervalos iguais (os rendimentos extremos de municípios com
área colhida mínima esticariam a escala), quebras naturais de Jenks (instáveis a cada
versão dos dados) e quantis por ano (a cor deixaria de ser comparável entre anos). O custo
das classes fixas é que, na soja, 69% dos municípios ficam na classe mais baixa em 1974 e
61% na mais alta em 2025. É a tendência tecnológica, que o mapa deve mostrar; o contraste
dentro de um mesmo ano diminui nos extremos, e a tabela traz os valores exatos. Por isso,
junto à legenda, uma frase diz que as classes são as mesmas em todos os anos e que as
cores podem ser comparadas de um ano para outro.

**Área colhida mínima no rendimento: 100 ha.** No coroplético do rendimento, um município
com poucos hectares colhidos entrava nas classes como qualquer outro e, se o município é
grande, pintava um polígono enorme com um número frágil. Em 2025, São Gabriel da
Cachoeira (AM), com 108.687 km², aparecia na classe de 3.200 kg/ha do milho com 5 ha
colhidos. Abaixo de 100 ha, o município ganha um estado próprio, "área colhida pequena
demais para comparar", com um pontilhado distinto da hachura de sem dado e dos tons da
rampa, e fica fora das classes e do cálculo dos limites. O valor exato continua no tooltip
e na tabela, com a indicação, e na tabela esses municípios vêm depois dos comparáveis
quando ela é ordenada pelo valor. A regra vale para todas as séries. O limite saiu dos
dados:
- **Valores repetidos:** a parcela de anos em que o município repete exatamente o
  rendimento do ano anterior (sinal de valor estimado, não medido) fica entre 25% e 47%
  abaixo de 100 ha e cai pela metade acima dele (soja de 30% para 15%, milho de 29% para
  17%, café beneficiado de 31% para 19%, comparando as faixas de 50 a 100 ha e de 100 ha ou
  mais). Abaixo de 5 ha, na soja e no café, a variação mediana de um ano para outro é zero,
  e quando muda, o rendimento costuma dobrar ou cair pela metade.
- **Extremos:** na soja, a parcela na classe mais baixa é de 52% a 68% abaixo de 20 ha,
  27% entre 50 e 100 ha e se estabiliza entre 17% e 24% a partir de 100 ha.
- **Peso no mapa e nos totais:** na soja, no milho e no café beneficiado e arábica, os
  municípios abaixo de 100 ha somam no máximo 1,2% da área colhida nos anos examinados,
  mas pintam até 22% do território no milho (1990) e até 57% no café beneficiado (2025).

Quantos municípios caem no estado próprio:

| Série | Municípios abaixo de 100 ha (de quantos têm rendimento) |
|---|---|
| Soja | 1980: 151 de 1.020; 1990: 129 de 1.234; 2000: 148 de 1.446; 2010: 121 de 1.800; 2025: 101 de 2.641 |
| Milho | 1980: 367 de 3.712; 1990: 447 de 4.242; 2000: 581 de 5.329; 2010: 712 de 5.176; 2025: 1.117 de 4.993 |
| Café em coco | 1980: 630 de 1.753; 1990: 721 de 1.940; 2001: 944 de 2.007 |
| Café beneficiado | 2010: 872 de 1.822; 2025: 666 de 1.361 |
| Café arábica | 2025: 529 de 1.100 |
| Café canéfora | 2025: 199 de 357 |

Os limites das classes mudam pouco na soja (1.700, 2.200, 2.700 e 3.200 kg/ha, iguais) e
mais no café, em que muitos municípios produzem pouco: no beneficiado, de 670, 960, 1.200 e
1.600 para 750, 1.100, 1.300 e 1.700 kg/ha. Alternativas descartadas: um limite por série
(mais difícil de explicar, e as medidas de estabilidade apontam para o mesmo valor em todas)
e um limite relativo, como a área colhida sobre a área do município, que trataria o
problema visual mas não a fragilidade do número. O valor de 100 ha não aparece na página,
porque todo número impresso vem do pacote de dados e ele ainda não está lá; entra no
catálogo no próximo ciclo de dados.

**Três estados que nunca se confundem.** Sem dado é hachura nos dois modos: uma textura,
que não se lê como um tom claro. No coroplético, o zero publicado é o primeiro passo da
rampa, com o rótulo "não produziu", os valores ocupam os outros cinco passos e o
rendimento de área colhida pequena tem o pontilhado; nos círculos, o zero é a ausência de
círculo sobre o tom claro do mapa base. A rampa e os
círculos usam os tons neutros da identidade, sem o marrom e o verde-azulado, que são da
seca e da água. A linha de fonte diz "Municípios sem dado aparecem hachurados, e não como
zero". O valor real da produção antes do primeiro ano deflacionado (1995 na soja e no
milho) aparece hachurado, sem círculos, com "não disponível" na legenda e a nota "O valor
real da produção só existe a partir de 1995", com o ano lido do arquivo. O café segue o
contrato: cada série tem os seus anos (em coco até 2001, beneficiado desde 2002, arábica e
canéfora desde 2012), a troca de série traz o ano para dentro da série e a linha do tempo
só percorre os anos dela, então nenhuma visão atravessa 2002. O rendimento é calculado no
navegador, como permite a regra 1 do contrato: produção ÷ área colhida do mesmo município e
ano, em kg/ha. Ele é sem dado se faltar uma das duas, e zero só quando a produção e a área
são zero. No tooltip e na tabela, o número cita a produção com a operação `yield`, e o
teste refaz a conta com a matriz de área.

**Projeção e geometria próprias.** O mapa usa a SIRGAS 2000 / Brazil Albers (EPSG:10857),
a cônica de áreas iguais do IBGE para o país (paralelos −2° e −22°, meridiano −54°): a
área de cada município na tela é proporcional à real, o que importa num mapa em que a cor
cobre a superfície. A malha é decodificada por um leitor próprio do TopoJSON
(`web/src/components/explore/geometry.ts`): cada arco é projetado uma vez, em unidades
fixas do mapa, e redimensionar a tela vira uma transformação afim, sem projetar de novo. A
fórmula é a do d3 (`geoConicEqualAreaRaw`), conferida num teste contra o
`geoConicEqualArea` com os mesmos parâmetros. O motivo é o tempo: com o `geoPath` do d3 e o
`topojson-client`, montar os caminhos levava 337 ms na máquina de desenvolvimento (1,6 s
com a CPU 4× mais lenta), porque cada polígono era projetado três vezes (enquadramento,
desenho e centroide), com reamostragem adaptativa, e tudo se repetia a cada
redimensionamento. Agora a decodificação leva cerca de 50 ms e o preparo dos caminhos
30 ms, fatiados em pedaços de até 12 ms, sem nenhuma tarefa longa na abertura. O
`topojson-client` saiu das dependências. Alternativas descartadas: SVG com 5.571 caminhos
(DOM pesado, e trocar o ano repintaria milhares de elementos) e WebGL (mais código e mais
JavaScript, sem ganho nesse tamanho de malha).

**Desenho em canvas, uma cor por vez, e o próximo ano adiantado.** Cada quadro tem uma
base (o coroplético, ou o mapa neutro sob os círculos) que pinta os municípios agrupados
por cor, num único caminho por cor, o que também elimina as frestas de antisserrilhado
entre vizinhos da mesma classe. As divisas das UFs ganham um halo na cor do fundo, para
aparecerem sobre o escuro e sobre o claro. Um canvas oculto, pintado na primeira passagem
do ponteiro, identifica o município sob o cursor, confirmado por um teste de ponto no
polígono, e os círculos são testados antes dele, do de cima para o de baixo. O município
em destaque é um caminho SVG fino, também com halo, com o contorno do círculo quando há
um, e a triangulação de Delaunay dos pontos representativos dá os vizinhos para as setas
do teclado. O custo de uma base está na rasterização dos preenchimentos, não no desenho em
si. Por isso, durante o play, a base do ano seguinte é desenhada e rasterizada no
intervalo em que o mapa está parado, e um ano com a mesma base do anterior reaproveita o
quadro. Cada passo dura 450 ms: as bases se misturam, e os círculos vão do raio antigo ao
novo, redesenhados a cada quadro. O que pesa num quadro de círculos é a rasterização, que
o navegador faz ao entregar o canvas (no celular simulado, até 45 ms por quadro com os
2.600 círculos da soja). Os círculos de até 1,5 px, que são a maioria, não têm contorno e
são os últimos da ordem, vão todos num único preenchimento. Durante o passo, eles entram
de uma vez, no tamanho novo, numa camada pronta sobreposta aos demais, e só os maiores
mudam de tamanho quadro a quadro. Abaixo de 1,5 px a mudança não se vê, e o último quadro
desenha todos. Com movimento reduzido, o passo é um salto. A linha do tempo nunca começa sozinha.

**Contorno primeiro, no próprio HTML.** No celular, a malha municipal (290 KiB) e a matriz
da soja (189 KiB) levam alguns segundos para chegar. Para a página não ficar vazia nesse
tempo, o contorno das UFs vai no HTML, gerado no build a partir de `geo/states.topo.json`,
no mesmo enquadramento da malha municipal e em unidades inteiras do mapa (5,5 KB com
gzip). A legenda já vinha no HTML. Os dois aparecem na primeira pintura, antes do
JavaScript, e também sem ele, com uma nota explicando que o mapa precisa de JavaScript.
Como as duas malhas são decodificadas no mesmo enquadramento e ajustadas à caixa pela
mesma margem, o contorno cai onde os municípios serão desenhados: um teste compara a caixa
do contorno com a dos pixels pintados no canvas, com tolerância de 3 px. Enquanto isso,
uma etiqueta discreta no centro do mapa diz "Carregando os municípios…", numa região
`role="status"`, com o grupo do mapa em `aria-busy`. Ela só aparece se a espera passar de
300 ms, para o leitor de tela não anunciar cada passo do play, e a barrinha animada fica
parada com movimento reduzido. Alternativa descartada: baixar o `geo/states.topo.json`
(13 KiB) depois que a ilha inicia, o que faria o contorno esperar o JavaScript e mais uma
ida à rede.

**Pré-cargas de dados com prioridade baixa.** A malha municipal e a matriz da visão
padrão são pré-carregadas no `<head>`, para chegarem junto com o script, mas com
`fetchpriority="low"`: as fontes, o CSS e o JavaScript passam na frente, e a primeira
pintura (título, contorno e legenda) não espera por elas. Com prioridade alta, o tempo
observado era o mesmo (LCP de 62 a 69 ms), mas a simulação de rede lenta do Lighthouse
contava os 529 KB dessas duas requisições como dependências do título, e a nota do celular
oscilava entre 0,78 e 0,96 com a máquina livre. Com prioridade baixa, ela ficou em 0,97 nas
três rodadas, e o mapa completo chegou cerca de 0,15 s depois no celular simulado.

**Desempenho medido.** `web/scripts/measure-explore.mjs` serve o `dist/` com gzip e mede
no perfil de celular do Lighthouse (412 px, DPR 1,75, CPU 4× mais lenta, 150 ms de
latência e 1,6 Mbit/s) e num computador sem limitação. Os momentos em que o contorno e o
mapa completo aparecem são os do primeiro quadro de pintura em que eles estão na tela.
O Chromium dos testes não usa GPU, então a rasterização é por software e os números são
pessimistas. A tabela traz a mediana de duas rodadas com a máquina quase livre (carga
média de 1,4 a 2,3). Numa rodada com carga de 0,7, antes da troca de prioridade, o desenho
da base no celular levou 16 ms e o mapa completo 4,1 s.

| Medida | Celular simulado | Computador |
|---|---|---|
| Contorno das UFs e legenda na tela (primeira pintura) | 0,52 s | 0,04 s |
| Mapa completo, círculos da produção | 4,3 s | 0,38 s |
| Mapa completo, coroplético do rendimento (duas matrizes) | 4,9 s | 0,40 s |
| Desenho da base (comandos) | 23 ms | 13 ms |
| Desenho de todos os círculos (2.600 na soja) | 4,4 ms | 2 ms |
| Desenho dos círculos num quadro de transição (só os maiores) | mediana 0,8 ms, p95 3,4 ms | mediana 0,6 ms, p95 1,5 ms |
| Quadros das transições dos círculos (10 anos) | 277, p95 16,8 ms, no máximo 1 de 33 ms | 280, todos ≤ 16,8 ms |
| Quadros das transições do coroplético (10 anos) | 280, todos ≤ 16,8 ms | 280, todos ≤ 16,8 ms |
| Base do ano seguinte, adiantada e rasterizada | 0,25 s | 0,08 s |
| Zoom em Minas Gerais (a maior malha estadual) | 1,5 s | 0,12 s |

Antes da camada dos círculos pequenos, com a máquina carregada, mais da metade dos quadros
das transições dos círculos no celular passava de 33 ms; com a máquina livre, cerca de 2%.

**Lighthouse e a carga da máquina.** O Explorar ficou com desempenho de 0,97 no celular nas
três rodadas (LCP de 911 ms, bloqueio de 194 a 205 ms) e de 0,99 a 1,00 no computador, com
684 KiB transferidos de 700 KiB do orçamento e 89 KiB de JavaScript de 160 KiB. A queda
para 0,84 numa rodada anterior teve duas causas. A primeira foi a carga da máquina: o
Lighthouse mede a velocidade da CPU a cada rodada (`benchmarkIndex`), que estava em cerca
de 1.000 naquelas rodadas e em cerca de 2.260 com a máquina livre, e o bloqueio da thread
principal caiu de 392–624 ms para 200–266 ms. A segunda foi a estimativa do LCP, explicada
no parágrafo das pré-cargas. Para caber no orçamento, a página não carrega a Sans Bold (a
legenda e o tooltip usam tamanho e cor, não peso), os nomes dos municípios só chegam na
primeira interação com o mapa ou a tabela e as malhas detalhadas só ao entrar numa UF.

**Filtros na frase, visão na URL e tabela.** O título é a frase do rascunho, com cada
filtro num `select` nativo dentro dela ("Cultura", "Medida" e "Ano" como nomes
acessíveis), sublinhado na cor do texto e com a largura da opção escolhida
(`field-sizing`, com medição em JavaScript onde não houver suporte). Nos totais, a frase
pergunta onde ("Onde se produz soja, em toneladas, em 2025"); no rendimento, quanto rende
("Quanto rende a soja, em quilos por hectare, em 2025"), com o artigo de cada cultura e os
mesmos filtros. Em telas estreitas o título diminui com a largura, até o tamanho de título
da identidade, e um teste percorre todas as culturas e medidas a 360 px e falha se a página
ganhar rolagem horizontal. O `select` nativo
funciona com teclado, leitor de tela e toque sem código extra; um menu próprio teria de
reimplementar tudo isso. A visão vai para a URL (`?serie=soja&medida=producao&ano=2025&uf=MT`)
com `replaceState`, sem encher o histórico, e é lida antes de qualquer download, então um
link permanente baixa só os dados da sua visão. O mapa é um grupo focável: as setas
percorrem os vizinhos, Enter abre a ficha, Esc fecha o tooltip (de qualquer ponto da
página, WCAG 1.4.13), e cada município escolhido é anunciado numa região `aria-live`. No
toque, o primeiro toque mostra o município e o segundo abre a ficha. "Ver como tabela"
mostra os mesmos dados da visão, ordenáveis pelo nome ou pelo valor (`aria-sort`), numa
região rolável que recebe foco, com cada nome levando à ficha. O espaço do painel lateral
(série do Brasil e ranking das UFs) e da decomposição área × produtividade fica reservado
para a parte B.
