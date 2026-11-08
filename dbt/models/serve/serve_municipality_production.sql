-- Production by municipality, published series and year, with the municipality's rank among
-- the producers of its immediate region, its state and Brazil. Only combinations with data
-- in the PAM: a missing row means "no data" (for example, a municipality created later), a
-- zero is a zero published by IBGE. Yield is not published here: the site computes it as
-- production / harvested area (sum / sum for any aggregate).
with production as (
    select
        fct.municipality_id,
        dim.state_id,
        dim.immediate_region_id,
        {{ serve_series('fct.crop', 'fct.year') }} as series,
        fct.year,
        fct.production_t,
        fct.harvested_area_ha,
        fct.planted_or_bearing_area_ha,
        fct.production_value_real_thousand_brl
    from {{ ref('fct_crop_production') }} as fct
    inner join {{ ref('dim_municipality') }} as dim
        on dim.municipality_id = fct.municipality_id
)

select
    municipality_id,
    state_id,
    immediate_region_id,
    series,
    year,
    {{ round_to_int('production_t') }} as production_t,
    {{ round_to_int('harvested_area_ha') }} as harvested_area_ha,
    {{ round_to_int('planted_or_bearing_area_ha') }} as planted_or_bearing_area_ha,
    -- Null before the Plano Real (1995): the real value does not exist there.
    {{ round_to_int('production_value_real_thousand_brl') }} as production_value_real_thousand_brl,
    -- Ranks by production among producers (ties share the rank); null for a zero.
    case when production_t > 0 then
        rank() over (partition by series, year order by production_t desc)
    end as rank_country,
    case when production_t > 0 then
        rank() over (partition by series, year, state_id order by production_t desc)
    end as rank_state,
    case when production_t > 0 then
        rank() over (partition by series, year, immediate_region_id order by production_t desc)
    end as rank_immediate_region
from production
