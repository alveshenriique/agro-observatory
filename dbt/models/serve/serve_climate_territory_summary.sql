-- Climate x yield association summary by immediate region and state (never by municipality).
-- `water_deficit_share` is the frequency of "seca na floração e enchimento" (the class of the
-- main finding, is_water_deficit: water balance z <= -1 in the critical window, flowering and
-- grain filling) among the years of the series: the drought risk shown for a region.
-- Anomalies and shares are fractions.
select
    territory_level,
    territory_id,
    territory_name,
    crop,
    trend_method,
    n_years,
    first_year,
    last_year,
    water_deficit_years,
    {{ round_to(as_float('water_deficit_years') ~ ' / nullif(n_years, 0)', 4) }} as water_deficit_share,
    {{ round_to('mean_anomaly_water_deficit_years', 4) }} as mean_anomaly_water_deficit_years,
    {{ round_to('mean_anomaly_no_water_deficit_years', 4) }} as mean_anomaly_no_water_deficit_years,
    {{ round_to('water_deficit_hit_rate', 4) }} as water_deficit_hit_rate,
    {{ round_to('negative_anomaly_share_all_years', 4) }} as negative_anomaly_share_all_years,
    {{ round_to('corr_water_balance_yield', 3) }} as corr_water_balance_yield,
    heat_stress_years,
    {{ round_to('mean_anomaly_heat_stress_years', 4) }} as mean_anomaly_heat_stress_years,
    {{ round_to('heat_stress_hit_rate', 4) }} as heat_stress_hit_rate,
    frost_years,
    {{ round_to('mean_anomaly_frost_years', 4) }} as mean_anomaly_frost_years,
    {{ round_to('frost_hit_rate', 4) }} as frost_hit_rate
from {{ ref('agg_climate_yield_association_summary') }}
where territory_level in ('immediate_region', 'state')
    and crop in ('soybean', 'coffee_arabica')
