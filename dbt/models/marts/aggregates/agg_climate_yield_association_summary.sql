-- Summary of the climate × yield association per territory × crop, over the years with both
-- a climate normal and a yield trend: correlations, mean yield anomaly in stress years versus
-- the others, and the hit rate (share of stress years with a negative anomaly). The share of
-- negative anomalies over all years is the baseline to compare the hit rate against.
with years as (
    select *
    from {{ ref('agg_climate_yield_association') }}
    where is_normal_available and is_trend_available
)

select
    territory_level,
    territory_id,
    territory_name,
    crop,
    max(trend_method) as trend_method,
    count(*) as n_years,
    min(harvest_year) as first_year,
    max(harvest_year) as last_year,
    corr(water_balance_z, yield_anomaly_pct) as corr_water_balance_yield,
    corr(hot_days_z, yield_anomaly_pct) as corr_hot_days_yield,
    corr(longest_dry_spell_z, yield_anomaly_pct) as corr_dry_spell_yield,
    count(*) filter (where yield_anomaly_pct < 0)::numeric / count(*) as negative_anomaly_share_all_years,

    count(*) filter (where is_water_deficit) as water_deficit_years,
    avg(yield_anomaly_pct) filter (where is_water_deficit) as mean_anomaly_water_deficit_years,
    avg(yield_anomaly_pct) filter (where not is_water_deficit) as mean_anomaly_no_water_deficit_years,
    count(*) filter (where is_water_deficit and yield_anomaly_pct < 0)::numeric
        / nullif(count(*) filter (where is_water_deficit), 0) as water_deficit_hit_rate,

    count(*) filter (where is_heat_stress) as heat_stress_years,
    avg(yield_anomaly_pct) filter (where is_heat_stress) as mean_anomaly_heat_stress_years,
    avg(yield_anomaly_pct) filter (where not is_heat_stress) as mean_anomaly_no_heat_stress_years,
    count(*) filter (where is_heat_stress and yield_anomaly_pct < 0)::numeric
        / nullif(count(*) filter (where is_heat_stress), 0) as heat_stress_hit_rate,

    count(*) filter (where is_frost) as frost_years,
    avg(yield_anomaly_pct) filter (where is_frost) as mean_anomaly_frost_years,
    avg(yield_anomaly_pct) filter (where not is_frost) as mean_anomaly_no_frost_years,
    count(*) filter (where is_frost and yield_anomaly_pct < 0)::numeric
        / nullif(count(*) filter (where is_frost), 0) as frost_hit_rate
from years
group by territory_level, territory_id, territory_name, crop
