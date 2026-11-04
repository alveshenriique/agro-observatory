-- Pivot PAM from one row per variable to one row per municipality × crop × year.
-- Materialized as a table: both marts read it, and the pivot scans ~5M staging rows.
{{ config(materialized='table') }}

{% set measures = [
    ('planted_area', 'planted_area_ha', 'planted_area_status'),
    ('harvested_area', 'harvested_area_ha', 'harvested_area_status'),
    ('production_quantity', 'production_t', 'production_status'),
    ('average_yield', 'ibge_yield_kg_ha', 'ibge_yield_status'),
    ('production_value', 'production_value_nominal_thousand', 'production_value_status'),
] %}

with pam as (
    select * from {{ ref('stg_ibge__pam') }}
)

select
    municipality_id,
    crop,
    year,

    {% for variable, value_column, status_column in measures %}
    max(case when variable = '{{ variable }}' then value end) as {{ value_column }},
    max(case when variable = '{{ variable }}' then value_status end) as {{ status_column }},
    {% endfor %}
    max(case when variable = 'production_value' then unit end) as production_value_unit,

    -- False when every variable is "..." or ".." (e.g. the municipality did not exist yet).
    -- Zeros and confidential values count as data.
    {{ dbt.bool_or("value_status not in ('not_available', 'not_applicable')") }} as has_data

from pam
group by municipality_id, crop, year
