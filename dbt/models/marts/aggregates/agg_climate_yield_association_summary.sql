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
    corr(heat_degree_days_z, yield_anomaly_pct) as corr_heat_degree_days_yield,
    -- Biennial crops: the same correlation with the alternative (OLS + parity) anomaly.
    corr(water_balance_z, biennial_ols_yield_anomaly_pct) as corr_water_balance_biennial_ols_yield,
    cast(count(case when yield_anomaly_pct < 0 then 1 end) as {{ dbt.type_float() }}) / count(*) as negative_anomaly_share_all_years,

    count(case when is_water_deficit then 1 end) as water_deficit_years,
    avg(case when is_water_deficit then yield_anomaly_pct end) as mean_anomaly_water_deficit_years,
    avg(case when not is_water_deficit then yield_anomaly_pct end) as mean_anomaly_no_water_deficit_years,
    cast(count(case when is_water_deficit and yield_anomaly_pct < 0 then 1 end) as {{ dbt.type_float() }})
        / nullif(count(case when is_water_deficit then 1 end), 0) as water_deficit_hit_rate,

    count(case when is_heat_stress then 1 end) as heat_stress_years,
    avg(case when is_heat_stress then yield_anomaly_pct end) as mean_anomaly_heat_stress_years,
    avg(case when not is_heat_stress then yield_anomaly_pct end) as mean_anomaly_no_heat_stress_years,
    cast(count(case when is_heat_stress and yield_anomaly_pct < 0 then 1 end) as {{ dbt.type_float() }})
        / nullif(count(case when is_heat_stress then 1 end), 0) as heat_stress_hit_rate,

    count(case when is_frost then 1 end) as frost_years,
    avg(case when is_frost then yield_anomaly_pct end) as mean_anomaly_frost_years,
    avg(case when not is_frost then yield_anomaly_pct end) as mean_anomaly_no_frost_years,
    cast(count(case when is_frost and yield_anomaly_pct < 0 then 1 end) as {{ dbt.type_float() }})
        / nullif(count(case when is_frost then 1 end), 0) as frost_hit_rate,
    avg(case when is_frost then biennial_ols_yield_anomaly_pct end) as mean_biennial_ols_anomaly_frost_years,
    avg(case when is_water_deficit then biennial_ols_yield_anomaly_pct end) as mean_biennial_ols_anomaly_water_deficit_years
from years
group by territory_level, territory_id, territory_name, crop
