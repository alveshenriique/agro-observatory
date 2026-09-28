-- Pivot PAM from one row per variable to one row per municipality × crop × year.
-- Materialized as a table: both marts read it, and the pivot scans ~5M staging rows.
{{ config(materialized='table') }}

with pam as (
    select * from {{ ref('stg_ibge__pam') }}
)

select
    municipality_id,
    crop,
    year,

    max(value) filter (where variable = 'planted_area') as planted_area_ha,
    max(value_status) filter (where variable = 'planted_area') as planted_area_status,

    max(value) filter (where variable = 'harvested_area') as harvested_area_ha,
    max(value_status) filter (where variable = 'harvested_area') as harvested_area_status,

    max(value) filter (where variable = 'production_quantity') as production_t,
    max(value_status) filter (where variable = 'production_quantity') as production_status,

    max(value) filter (where variable = 'average_yield') as ibge_yield_kg_ha,
    max(value_status) filter (where variable = 'average_yield') as ibge_yield_status,

    max(value) filter (where variable = 'production_value') as production_value_nominal_thousand,
    max(value_status) filter (where variable = 'production_value') as production_value_status,
    max(unit) filter (where variable = 'production_value') as production_value_unit,

    -- False when every variable is "..." or ".." (e.g. the municipality did not exist yet).
    -- Zeros and confidential values count as data.
    bool_or(value_status not in ('not_available', 'not_applicable')) as has_data

from pam
group by municipality_id, crop, year
