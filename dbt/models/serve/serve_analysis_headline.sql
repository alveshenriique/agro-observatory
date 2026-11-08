-- The main finding, in one row: soybean yield anomaly in water-deficit years ("seca na
-- floração e enchimento") versus the other years, over every state-year with a climate normal
-- and a yield trend, and the immediate regions where the water balance and the yield anomaly
-- move together. The same numbers as the README chart (scripts/make_readme_chart.py reads
-- this model). Anomalies and shares are fractions.
with state_years as (
    select
        harvest_year,
        yield_anomaly_pct,
        coalesce(is_water_deficit, false) as is_water_deficit
    from {{ ref('agg_climate_yield_association') }}
    where crop = 'soybean' and territory_level = 'state'
        and is_normal_available and is_trend_available
),

regions as (
    select
        count(*) as regions_with_correlation,
        sum(case when corr_water_balance_yield > 0 then 1 else 0 end)
            as regions_with_positive_correlation
    from {{ ref('agg_climate_yield_association_summary') }}
    where crop = 'soybean' and territory_level = 'immediate_region'
        and corr_water_balance_yield is not null
),

finding as (
    select
        count(*) as state_years,
        sum(case when is_water_deficit then 1 else 0 end) as water_deficit_state_years,
        min(harvest_year) as first_year,
        max(harvest_year) as last_year,
        avg(case when is_water_deficit then yield_anomaly_pct end) as mean_anomaly_water_deficit_years,
        avg(case when not is_water_deficit then yield_anomaly_pct end) as mean_anomaly_other_years,
        avg(case when is_water_deficit then
            case when yield_anomaly_pct < 0 then 1.0 else 0.0 end
        end) as below_trend_share_water_deficit_years,
        avg(case when yield_anomaly_pct < 0 then 1.0 else 0.0 end) as below_trend_share_all_years
    from state_years
)

select
    'soybean' as crop,
    finding.state_years,
    finding.water_deficit_state_years,
    finding.first_year,
    finding.last_year,
    {{ round_to('finding.mean_anomaly_water_deficit_years', 4) }} as mean_anomaly_water_deficit_years,
    {{ round_to('finding.mean_anomaly_other_years', 4) }} as mean_anomaly_other_years,
    {{ round_to('finding.below_trend_share_water_deficit_years', 4) }} as below_trend_share_water_deficit_years,
    {{ round_to('finding.below_trend_share_all_years', 4) }} as below_trend_share_all_years,
    regions.regions_with_positive_correlation,
    regions.regions_with_correlation
from finding
cross join regions
