-- Climate x yield association by year, only for immediate regions and states: the published
-- data never associates climate and yield at the municipal level. Only soybean and arabica
-- coffee (corn is out of the climate analysis), and only from producing municipalities.
-- `yield_anomaly` is the mart's yield_anomaly_pct, a fraction (-0.42 = 42% below the trend).
select
    territory_level,
    territory_id,
    territory_name,
    crop,
    harvest_year,
    primary_window,
    municipalities,
    is_normal_available,
    is_trend_available,
    is_territory_standardized,
    {{ round_to('water_balance_z', 2) }} as water_balance_z,
    {{ round_to('precipitation_pct_of_normal', 1) }} as precipitation_pct_of_normal,
    {{ round_to('hot_days_z', 2) }} as hot_days_z,
    {{ round_to('hot_days_anomaly_days', 1) }} as hot_days_anomaly_days,
    {{ round_to('heat_degree_days_z', 2) }} as heat_degree_days_z,
    {{ round_to('longest_dry_spell_z', 2) }} as longest_dry_spell_z,
    {{ round_to('frost_tmin_min_c', 1) }} as frost_tmin_min_c,
    {{ round_to('frost_area_share', 4) }} as frost_area_share,
    is_water_deficit,
    is_heat_stress,
    is_frost,
    {{ round_to('yield_kg_ha', 0) }} as yield_kg_ha,
    {{ round_to('trend_yield_kg_ha', 0) }} as trend_yield_kg_ha,
    trend_method,
    {{ round_to('yield_anomaly_pct', 4) }} as yield_anomaly
from {{ ref('agg_climate_yield_association') }}
where territory_level in ('immediate_region', 'state')
    and crop in ('soybean', 'coffee_arabica')
