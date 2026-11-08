-- Production of Brazil, its macro-regions, states and immediate regions by published series
-- and year: sums of the municipal rows. These are the only territorial aggregates the site
-- shows; it computes yield from them as production / harvested area (a ratio of sums).
with production as (
    select
        dim.region_id,
        dim.region_name,
        dim.state_id,
        dim.state_name,
        dim.immediate_region_id,
        dim.immediate_region_name,
        {{ serve_series('fct.crop', 'fct.year') }} as series,
        fct.year,
        fct.production_t,
        fct.harvested_area_ha,
        fct.planted_or_bearing_area_ha,
        fct.production_value_real_thousand_brl
    from {{ ref('fct_crop_production') }} as fct
    inner join {{ ref('dim_municipality') }} as dim
        on dim.municipality_id = fct.municipality_id
),

territories as (
    select 'country' as territory_level, 1 as territory_id, 'Brasil' as territory_name, production.*
    from production
    union all
    select 'macro_region', region_id, region_name, production.*
    from production
    union all
    select 'state', state_id, state_name, production.*
    from production
    union all
    select 'immediate_region', immediate_region_id, immediate_region_name, production.*
    from production
)

select
    territory_level,
    territory_id,
    territory_name,
    series,
    year,
    {{ round_to_int('sum(production_t)') }} as production_t,
    {{ round_to_int('sum(harvested_area_ha)') }} as harvested_area_ha,
    {{ round_to_int('sum(planted_or_bearing_area_ha)') }} as planted_or_bearing_area_ha,
    -- Null before 1995 (no real value), like the municipal rows.
    {{ round_to_int('sum(production_value_real_thousand_brl)') }} as production_value_real_thousand_brl,
    count(*) as municipalities_with_data,
    sum(case when production_t > 0 then 1 else 0 end) as producing_municipalities
from territories
group by territory_level, territory_id, territory_name, series, year
