-- Growth decomposition (area x yield) with the published series. Coffee anchors start in
-- 2005, after the unit break, so coffee pairs are "coffee_processed" at both ends (checked by
-- assert_serve_series_respect_coffee_break).
select
    {{ serve_series('crop', 'start_anchor - 1') }} as series,
    territory_level,
    territory_id,
    territory_name,
    start_anchor,
    end_anchor,
    start_period,
    end_period,
    {{ round_to_int('start_production_t') }} as start_production_t,
    {{ round_to_int('end_production_t') }} as end_production_t,
    {{ round_to_int('start_harvested_area_ha') }} as start_harvested_area_ha,
    {{ round_to_int('end_harvested_area_ha') }} as end_harvested_area_ha,
    {{ round_to('start_yield_kg_ha', 0) }} as start_yield_kg_ha,
    {{ round_to('end_yield_kg_ha', 0) }} as end_yield_kg_ha,
    {{ round_to('start_share_of_national_production', 4) }} as start_share_of_national_production,
    is_low_base,
    {{ round_to('ln_production_growth', 4) }} as ln_production_growth,
    {{ round_to('ln_area_effect', 4) }} as ln_area_effect,
    {{ round_to('ln_yield_effect', 4) }} as ln_yield_effect,
    {{ round_to('area_share_of_growth', 4) }} as area_share_of_growth,
    {{ round_to('yield_share_of_growth', 4) }} as yield_share_of_growth
from {{ ref('agg_production_growth_decomposition') }}
