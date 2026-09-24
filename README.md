# Agro Observatory

Pipeline de dados sobre a produção agrícola brasileira. Cruza a Produção Agrícola Municipal (PAM) do IBGE com o IPCA do Banco Central para analisar a evolução de área, produção e produtividade de soja, milho e café por município e região. Numa fase posterior, incorpora dados meteorológicos do INMET.

## Decisões técnicas

### Stack do MVP

A ingestão é feita em Python 3.12, com ambiente e dependências gerenciados pelo uv. Os dados brutos das APIs são salvos primeiro em arquivos Parquet (camada raw) e só depois carregados em um PostgreSQL local, rodando em Docker, que funciona como warehouse de desenvolvimento. As transformações até o modelo dimensional ficam no dbt-core. A camada raw em arquivo permite reprocessar e auditar os dados sem chamar as APIs de novo, e deixa a carga idempotente. O Parquet foi escolhido por preservar os tipos e ocupar pouco espaço.

Alternativas descartadas. DuckDB é mais simples, mas o PostgreSQL tem conexão nativa com o Power BI e fica mais próximo de um warehouse real, o que facilita a migração futura para cloud. pip e Poetry perderam para o uv, que reúne lockfile, gestão da versão do Python e muito mais velocidade numa única ferramenta. Gravar com pandas direto no banco, sem camada raw, acoplaria extração e carga e obrigaria a baixar tudo de novo das APIs a cada erro ou mudança de schema. CSV foi descartado por não preservar tipos. SQL avulso no lugar do dbt perderia a linhagem, os testes de dados e a documentação que o dbt já oferece.
