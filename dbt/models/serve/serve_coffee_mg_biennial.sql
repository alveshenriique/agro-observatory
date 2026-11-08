-- Arabica coffee bienniality in Minas Gerais, with the published series names (the mart's
-- coffee_total_in_husk and coffee_total_processed are already split at 2002).
select
    case series
        when 'coffee_total_in_husk' then 'coffee_in_husk'
        when 'coffee_total_processed' then 'coffee_processed'
        else series
    end as series,
    year,
    production_unit,
    {{ round_to_int('production_t') }} as production_t,
    {{ round_to_int('harvested_area_ha') }} as harvested_area_ha,
    {{ round_to('yield_kg_ha', 0) }} as yield_kg_ha,
    {{ round_to('production_change_vs_previous_year', 4) }} as production_change_vs_previous_year,
    {{ round_to_int('production_centered_trend_t') }} as production_centered_trend_t,
    {{ round_to('production_ratio_to_trend', 4) }} as production_ratio_to_trend,
    {{ round_to('yield_centered_trend_kg_ha', 0) }} as yield_centered_trend_kg_ha,
    {{ round_to('yield_ratio_to_trend', 4) }} as yield_ratio_to_trend,
    cycle_phase,
    yield_cycle_phase
from {{ ref('agg_coffee_mg_biennial') }}
