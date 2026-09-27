with source as (
    select * from {{ source('raw', 'localities') }}
)

select
    id::integer as municipality_id,
    nome as municipality_name,

    -- Current regional division (2017): immediate and intermediate geographic regions.
    "regiao-imediata__id"::integer as immediate_region_id,
    "regiao-imediata__nome" as immediate_region_name,
    "regiao-imediata__regiao-intermediaria__id"::integer as intermediate_region_id,
    "regiao-imediata__regiao-intermediaria__nome" as intermediate_region_name,

    -- Previous regional division (1989): micro and mesoregions. Null for municipalities
    -- created after it was discontinued (e.g. Boa Esperança do Norte - MT).
    "microrregiao__id"::integer as microregion_id,
    "microrregiao__nome" as microregion_name,
    "microrregiao__mesorregiao__id"::integer as mesoregion_id,
    "microrregiao__mesorregiao__nome" as mesoregion_name,

    -- State and region come from the current division, which every municipality has.
    "regiao-imediata__regiao-intermediaria__UF__id"::integer as state_id,
    "regiao-imediata__regiao-intermediaria__UF__sigla" as state_abbreviation,
    "regiao-imediata__regiao-intermediaria__UF__nome" as state_name,
    "regiao-imediata__regiao-intermediaria__UF__regiao__id"::integer as region_id,
    "regiao-imediata__regiao-intermediaria__UF__regiao__sigla" as region_abbreviation,
    "regiao-imediata__regiao-intermediaria__UF__regiao__nome" as region_name,

    -- Kept only to check that both divisions agree on the state (see tests).
    "microrregiao__mesorregiao__UF__id"::integer as mesoregion_state_id,

    _ingested_at as ingested_at,
    _loaded_at as loaded_at
from source
