# Agro Observatory

Pipeline de dados sobre a produção agrícola brasileira. Cruza a Produção Agrícola Municipal (PAM) do IBGE com o IPCA do Banco Central para analisar a evolução de área, produção e produtividade de soja, milho e café por município e região. Numa fase posterior, incorpora dados meteorológicos do INMET.

## Decisões técnicas

### Stack do MVP

A ingestão é feita em Python 3.12, com ambiente e dependências gerenciados pelo uv. Os dados brutos das APIs são salvos primeiro em arquivos Parquet (camada raw) e só depois carregados em um PostgreSQL local, rodando em Docker, que funciona como warehouse de desenvolvimento. As transformações até o modelo dimensional ficam no dbt-core. A camada raw em arquivo permite reprocessar e auditar os dados sem chamar as APIs de novo, e deixa a carga idempotente. O Parquet foi escolhido por preservar os tipos e ocupar pouco espaço.

Alternativas descartadas. DuckDB é mais simples, mas o PostgreSQL tem conexão nativa com o Power BI e fica mais próximo de um warehouse real, o que facilita a migração futura para cloud. pip e Poetry perderam para o uv, que reúne lockfile, gestão da versão do Python e muito mais velocidade numa única ferramenta. Gravar com pandas direto no banco, sem camada raw, acoplaria extração e carga e obrigaria a baixar tudo de novo das APIs a cada erro ou mudança de schema. CSV foi descartado por não preservar tipos. SQL avulso no lugar do dbt perderia a linhagem, os testes de dados e a documentação que o dbt já oferece.

### Reingestão dos anos mais recentes da PAM

A ingestão da PAM é idempotente: cada combinação de cultura e ano vira uma partição Parquet, e partições já existentes são puladas. A exceção são os 2 anos mais recentes disponíveis, que são sempre baixados de novo e sobrescritos. O IBGE revisa os dados da PAM depois da primeira divulgação, então pular esses anos congelaria números preliminares. O "ano mais recente" vem da API de metadados do IBGE a cada execução, e não de um valor fixo no código. Existe também a opção `--force`, que baixa tudo de novo.

Alternativas descartadas. Pular toda partição existente deixaria a camada raw desatualizada sem nenhum aviso. Baixar tudo a cada execução garante dados atualizados, mas custa 184 requisições (de 30 a 60 minutos) para mudar, na prática, só os anos recentes. Comparar hashes do conteúdo exigiria baixar os dados de qualquer forma, então não economizaria requisições.

### Localidades como snapshot da malha atual

A lista de municípios, com UF, região, mesorregião/microrregião e região intermediária/imediata, é baixada da API de Localidades do IBGE como uma foto da malha territorial atual. Cada execução substitui a anterior, sem guardar versões. Isso funciona porque a PAM também publica toda a série histórica na malha atual (municípios criados depois aparecem como "..." nos anos anteriores), então os dois lados do cruzamento usam a mesma referência territorial.

Alternativas descartadas. Guardar um histórico da malha (dimensão de mudança lenta, tipo 2) só teria valor se os fatos viessem em malhas diferentes a cada ano, o que não acontece aqui. O custo é que, se o IBGE redesenhar uma divisão regional, a mudança vale retroativamente para toda a série. Para acompanhar a evolução da malha seria preciso ingerir as tabelas de alterações territoriais do IBGE, o que foge do escopo do MVP.

### Carga da camada raw no Postgres

Cada arquivo Parquet é carregado no schema `raw` com `COPY`, numa transação própria. Na PAM, a transação apaga as linhas daquela partição (cultura e ano) e copia o arquivo. Em Localidades e IPCA, a tabela é esvaziada e recarregada. Se a carga falhar no meio, a transação é desfeita e o banco continua com a versão anterior completa. Para não recarregar 5 milhões de linhas a cada execução, o `_ingested_at` de cada arquivo é comparado com o que já está no banco, e só os arquivos reingeridos desde a última carga são recarregados; `--force` recarrega tudo. Linhas de arquivos que não existem mais no disco geram um aviso na carga e só são apagadas com `--prune`, para que um arquivo removido por engano não apague dados do banco em silêncio. As tabelas raw não têm índices, chaves nem tipagem: isso é papel do dbt.

Alternativas descartadas. `pandas.to_sql` e inserts linha a linha são uma ou duas ordens de grandeza mais lentos que `COPY` e, no caso do pandas, trariam uma dependência só para isso. Um índice em `_source_file` aceleraria o `DELETE` por partição, mas a raw deve ficar sem índices, e com a carga pulando arquivos inalterados o `DELETE` só roda nas poucas partições que mudaram. Comparar hashes do conteúdo seria mais preciso do que comparar `_ingested_at`, mas exigiria ler cada arquivo inteiro a cada execução, e o `_ingested_at` já muda exatamente quando a ingestão regrava um arquivo.

### Valores especiais da PAM: valor numérico e coluna de status

O IBGE publica símbolos no lugar de números: "-" (zero absoluto), "0" (zero resultante de arredondamento), "..." (dado não disponível), ".." (não se aplica) e "X" (omitido por sigilo). No staging, cada valor vira um número em `value` (0 para os dois tipos de zero, nulo para os demais símbolos) e um `value_status` (`reported`, `absolute_zero`, `rounded_zero`, `not_available`, `not_applicable`, `confidential`). Assim `value` pode ser somado e agregado diretamente, e a informação de por que um número é zero ou está ausente continua disponível. Isso importa: na PAM, 46% dos registros são zero absoluto e 13% são "não disponível", e tratar os dois do mesmo jeito distorceria médias e contagens de municípios produtores. Um teste garante que `value` é nulo exatamente quando o status indica ausência de número.

Alternativas descartadas. Converter todos os símbolos para nulo perderia a diferença entre "o município não produz" e "não há dado", que é justamente o que separa um município fora da fronteira agrícola de um município ainda inexistente no ano. Converter todos para 0 inflaria o número de municípios com produção zero e puxaria médias para baixo. Manter só o texto original empurraria esse parsing para cada consulta dos marts.
