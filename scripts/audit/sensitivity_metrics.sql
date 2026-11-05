-- Metrics used by the sensitivity analysis (scripts/audit/run_sensitivity.sh). Read-only.
SET statement_timeout = '300s';
\pset footer off
\echo '== soybean, state level, stacked (years with normal and trend)'
select count(*) as uf_years,
       round(corr(water_balance_z, yield_anomaly_pct)::numeric, 3) as corr_wb,
       round(100 * avg(yield_anomaly_pct) filter (where is_water_deficit)) as anom_deficit_pct,
       round(100 * avg(yield_anomaly_pct) filter (where not is_water_deficit)) as anom_other_pct,
       count(*) filter (where is_water_deficit) as deficit_years,
       round(100 * (count(*) filter (where is_water_deficit and yield_anomaly_pct < 0))::numeric / nullif(count(*) filter (where is_water_deficit), 0)) as deficit_hit_rate_pct,
       count(*) filter (where is_heat_stress) as heat_years,
       round(100 * (count(*) filter (where is_heat_stress and yield_anomaly_pct < 0))::numeric / nullif(count(*) filter (where is_heat_stress), 0)) as heat_hit_rate_pct,
       round(100 * (count(*) filter (where yield_anomaly_pct < 0))::numeric / count(*)) as negative_share_pct
from marts.agg_climate_yield_association
where crop = 'soybean' and territory_level = 'state' and is_normal_available and is_trend_available;
\echo '== soybean, immediate regions: correlation distribution and hit rates'
select count(*) as regions,
       round(percentile_cont(0.5) within group (order by corr_water_balance_yield)::numeric, 3) as median_corr_wb,
       count(*) filter (where corr_water_balance_yield > 0) as positive_corr,
       round(percentile_cont(0.5) within group (order by corr_hot_days_yield)::numeric, 3) as median_corr_heat,
       round(avg(water_deficit_hit_rate)::numeric, 3) as avg_deficit_hit_rate,
       round(avg(negative_anomaly_share_all_years)::numeric, 3) as avg_negative_share
from marts.agg_climate_yield_association_summary
where crop = 'soybean' and territory_level = 'immediate_region' and n_years >= 15;
\echo '== known events: anomaly sign and expected stress flag'
select e.crop, e.territory_name as uf, e.harvest_year as year, e.event_type,
       round(100 * a.yield_anomaly_pct) as anomaly_pct,
       round(a.water_balance_z::numeric, 2) as wb_z, round(a.hot_days_z::numeric, 2) as heat_z,
       round(a.frost_area_share::numeric, 2) as frost_share,
       case e.event_type when 'water_deficit' then a.is_water_deficit when 'frost' then a.is_frost else a.is_heat_stress end as flag
from seeds.known_climate_events e
left join marts.agg_climate_yield_association a
  on a.crop = e.crop and a.territory_level = e.territory_level and a.territory_name = e.territory_name and a.harvest_year = e.harvest_year
order by e.crop desc, e.harvest_year, e.territory_name;
\echo '== coffee MG: frost share and flags per year'
select harvest_year, round(frost_area_share::numeric, 2) as frost_share, is_frost, round(water_balance_z::numeric,2) as wb_z, is_water_deficit, round(100*yield_anomaly_pct) as anomaly_pct
from marts.agg_climate_yield_association where crop = 'coffee_arabica' and territory_level = 'state' order by 1;
\echo '== soybean critical window: days per state (first window row of 2024)'
select state_abbreviation, days_in_window from intermediate.int_climate__window_indicators
where crop='soybean' and window_name='critical' and harvest_year=2024 group by 1,2 order by 1;
