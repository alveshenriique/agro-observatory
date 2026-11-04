-- Source columns are named after the API path (e.g. "regiao-imediata__UF__sigla"), which
-- needs quoting on Postgres and a rename on BigQuery: source_column() handles both.
with source as (
    select * from {{ source('raw', 'localities') }}
)

select
    cast(id as {{ dbt.type_int() }}) as municipality_id,
    nome as municipality_name,

    -- Current regional division (2017): immediate and intermediate geographic regions.
    cast({{ source_column('regiao-imediata__id') }} as {{ dbt.type_int() }}) as immediate_region_id,
    {{ source_column('regiao-imediata__nome') }} as immediate_region_name,
    cast({{ source_column('regiao-imediata__regiao-intermediaria__id') }} as {{ dbt.type_int() }})
        as intermediate_region_id,
    {{ source_column('regiao-imediata__regiao-intermediaria__nome') }} as intermediate_region_name,

    -- Previous regional division (1989): micro and mesoregions. Null for municipalities
    -- created after it was discontinued (e.g. Boa Esperança do Norte - MT).
    cast({{ source_column('microrregiao__id') }} as {{ dbt.type_int() }}) as microregion_id,
    {{ source_column('microrregiao__nome') }} as microregion_name,
    cast({{ source_column('microrregiao__mesorregiao__id') }} as {{ dbt.type_int() }}) as mesoregion_id,
    {{ source_column('microrregiao__mesorregiao__nome') }} as mesoregion_name,

    -- State and region come from the current division, which every municipality has.
    cast({{ source_column('regiao-imediata__regiao-intermediaria__UF__id') }} as {{ dbt.type_int() }})
        as state_id,
    {{ source_column('regiao-imediata__regiao-intermediaria__UF__sigla') }} as state_abbreviation,
    {{ source_column('regiao-imediata__regiao-intermediaria__UF__nome') }} as state_name,
    cast({{ source_column('regiao-imediata__regiao-intermediaria__UF__regiao__id') }} as {{ dbt.type_int() }})
        as region_id,
    {{ source_column('regiao-imediata__regiao-intermediaria__UF__regiao__sigla') }} as region_abbreviation,
    {{ source_column('regiao-imediata__regiao-intermediaria__UF__regiao__nome') }} as region_name,

    -- Kept only to check that both divisions agree on the state (see tests).
    cast({{ source_column('microrregiao__mesorregiao__UF__id') }} as {{ dbt.type_int() }})
        as mesoregion_state_id,

    _ingested_at as ingested_at,
    _loaded_at as loaded_at
from source
