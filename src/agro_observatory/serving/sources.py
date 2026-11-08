"""Attribution of every data source, published in catalog.json for the site to display.

`attribution_pt` is the citation each source asks for. Basis of the terms (checked in
2026-11-07): IBGE content is public domain on condition that the source is cited (official
answer of IBGE's service desk, 2009, reproduced on the OpenStreetMap Brasil list); the IPCA is
computed by IBGE and distributed by the Banco Central's SGS (the BCB open data portal lists its
own SGS series under the ODbL; series 433 has no catalogue entry of its own); BR-DWGD's authors
ask for the citation of Xavier et al. (2022) and declare no licence; CONAB publications may be
reproduced provided the source is cited.
"""

from __future__ import annotations

SOURCES: dict[str, dict] = {
    "ibge_pam": {
        "name_pt": "Produção Agrícola Municipal (PAM), tabela 5457 do SIDRA",
        "publisher": "IBGE – Instituto Brasileiro de Geografia e Estatística",
        "url": "https://sidra.ibge.gov.br/tabela/5457",
        "attribution_pt": "Fonte: IBGE, Produção Agrícola Municipal (PAM), tabela 5457 do SIDRA.",
        "terms_pt": "Domínio público, com a citação do IBGE como fonte.",
        "used_for_pt": (
            "Produção, áreas e valor da produção por município; agregados Brasil e UF da mesma "
            "tabela na validação."
        ),
    },
    "ibge_localities": {
        "name_pt": "API de Localidades (divisão territorial)",
        "publisher": "IBGE – Instituto Brasileiro de Geografia e Estatística",
        "url": "https://servicodados.ibge.gov.br/api/docs/localidades",
        "attribution_pt": "Fonte: IBGE, API de Localidades.",
        "terms_pt": "Domínio público, com a citação do IBGE como fonte.",
        "used_for_pt": "Municípios, UFs, regiões imediatas e intermediárias (divisão atual).",
    },
    "ibge_mesh": {
        "name_pt": "Malha municipal (API de Malhas v4, qualidade máxima)",
        "publisher": "IBGE – Instituto Brasileiro de Geografia e Estatística",
        "url": "https://servicodados.ibge.gov.br/api/docs/malhas?versao=4",
        "attribution_pt": "Fonte: IBGE, Malha Municipal (simplificada para a web).",
        "terms_pt": "Domínio público, com a citação do IBGE como fonte.",
        "used_for_pt": "Mapas (polígonos simplificados) e o ponto representativo dos municípios.",
    },
    "bcb_ipca": {
        "name_pt": "IPCA, variação mensal (série 433 do SGS)",
        "publisher": "IBGE (índice), distribuído pelo Banco Central do Brasil (SGS)",
        "url": "https://www3.bcb.gov.br/sgspub/",
        "attribution_pt": (
            "Fonte: IBGE, Índice Nacional de Preços ao Consumidor Amplo (IPCA), obtido no Sistema "
            "Gerenciador de Séries Temporais do Banco Central do Brasil, série 433."
        ),
        "terms_pt": (
            "O IPCA é produzido pelo IBGE (domínio público, com citação da fonte); o Banco "
            "Central publica as suas séries do SGS sob a licença ODbL."
        ),
        "used_for_pt": "Deflação do valor da produção para reais do ano-base.",
    },
    "brdwgd": {
        "name_pt": "BR-DWGD v3.2.4, Brazilian Daily Weather Gridded Data",
        "publisher": "Xavier, A. C., Scanlon, B. R., King, C. W. e Alves, A. I.",
        "url": "https://sites.google.com/site/alexandrecandidoxavierufes/brazilian-daily-weather-gridded-data",
        "attribution_pt": (
            "Xavier, A. C., Scanlon, B. R., King, C. W., & Alves, A. I. (2022). New improved "
            "Brazilian daily weather gridded data (1961–2020). International Journal of "
            "Climatology, 42(16), 8390–8404. https://doi.org/10.1002/joc.7731"
        ),
        "terms_pt": "Os autores pedem a citação do artigo acima; não declaram licença.",
        "used_for_pt": (
            "Chuva, temperatura e evapotranspiração diárias, agregadas por município e resumidas "
            "por região imediata e UF."
        ),
    },
    "conab_calendar": {
        "name_pt": "Calendário de Plantio e Colheita de Grãos no Brasil 2022",
        "publisher": "Conab – Companhia Nacional de Abastecimento",
        "url": "https://www.gov.br/conab/pt-br",
        "attribution_pt": (
            "Fonte: Conab, Calendário de Plantio e Colheita de Grãos no Brasil (2022)."
        ),
        "terms_pt": "Reprodução permitida desde que citada a fonte.",
        "used_for_pt": "Janelas de floração e enchimento da soja por UF.",
    },
    "conab_series": {
        "name_pt": "Série histórica das safras de grãos (Portal de Informações)",
        "publisher": "Conab – Companhia Nacional de Abastecimento",
        "url": "https://portaldeinformacoes.conab.gov.br/",
        "attribution_pt": (
            "Fonte: Conab, Série Histórica das Safras, Portal de Informações da Conab."
        ),
        "terms_pt": "Reprodução permitida desde que citada a fonte.",
        "used_for_pt": "Validação externa da soja por UF (área plantada e produção).",
    },
}
