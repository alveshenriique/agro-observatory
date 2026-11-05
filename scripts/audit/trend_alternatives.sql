-- Audit, ad hoc (not a model): alternative yield-trend methods compared with the ones in
-- int_yield__territory_trend, using the climate anomalies already in the association mart.
-- Soybean: OLS log-linear (current) vs Theil-Sen (median of pairwise slopes, robust to drought
-- years). Arabica coffee in MG: centered 2x2 moving average (current) vs log-linear OLS with a
-- biennial term (year parity dummy). Run with:
--   docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q' < scripts/audit/trend_alternatives.sql
SET statement_timeout = '300s';
\pset footer off

-- ---------- Soybean: Theil-Sen vs OLS, state level ----------
create temp table soy_years as
select territory_level, territory_id, territory_name, harvest_year, yield_kg_ha, harvested_area_ha
from intermediate.int_yield__territory_trend
where crop = 'soybean' and harvest_year between 1991 and 2025 and harvested_area_ha >= 1000 and yield_kg_ha > 0;

create temp table theil_sen as
with pairs as (
  select a.territory_level, a.territory_id,
         (ln(b.yield_kg_ha) - ln(a.yield_kg_ha)) / (b.harvest_year - a.harvest_year) as slope
  from soy_years a join soy_years b
    on b.territory_level = a.territory_level and b.territory_id = a.territory_id and b.harvest_year > a.harvest_year),
slopes as (
  select territory_level, territory_id, percentile_cont(0.5) within group (order by slope) as slope
  from pairs group by 1, 2),
intercepts as (  -- median of (ln y - slope * year), the usual Theil-Sen intercept
  select y.territory_level, y.territory_id, s.slope,
         percentile_cont(0.5) within group (order by ln(y.yield_kg_ha) - s.slope * y.harvest_year) as intercept,
         count(*) as n_years
  from soy_years y join slopes s using (territory_level, territory_id) group by 1, 2, 3)
select y.territory_level, y.territory_id, y.territory_name, y.harvest_year,
       y.yield_kg_ha / exp(i.intercept + i.slope * y.harvest_year) - 1 as ts_anomaly_pct,
       exp(i.slope) - 1 as ts_growth
from soy_years y join intercepts i using (territory_level, territory_id) where i.n_years >= 15;

\echo '== soybean state level: OLS vs Theil-Sen anomalies (stacked)'
select count(*) as uf_years,
       round(corr(a.yield_anomaly_pct, t.ts_anomaly_pct)::numeric, 3) as corr_ols_ts,
       round(avg(abs(a.yield_anomaly_pct - t.ts_anomaly_pct))::numeric * 100, 1) as mean_abs_diff_pct,
       round(100 * (count(*) filter (where a.is_water_deficit and a.yield_anomaly_pct < 0))::numeric / nullif(count(*) filter (where a.is_water_deficit), 0)) as ols_hit_rate,
       round(100 * (count(*) filter (where a.is_water_deficit and t.ts_anomaly_pct < 0))::numeric / nullif(count(*) filter (where a.is_water_deficit), 0)) as ts_hit_rate,
       round(100 * (count(*) filter (where a.yield_anomaly_pct < 0))::numeric / count(*)) as ols_negative_share,
       round(100 * (count(*) filter (where t.ts_anomaly_pct < 0))::numeric / count(*)) as ts_negative_share,
       round(corr(a.water_balance_z, a.yield_anomaly_pct)::numeric, 3) as ols_corr_wb,
       round(corr(a.water_balance_z, t.ts_anomaly_pct)::numeric, 3) as ts_corr_wb
from marts.agg_climate_yield_association a
join theil_sen t on t.territory_level = a.territory_level and t.territory_id = a.territory_id and t.harvest_year = a.harvest_year
where a.crop = 'soybean' and a.territory_level = 'state' and a.is_normal_available and a.is_trend_available;

\echo '== soybean: known events, OLS vs Theil-Sen'
select e.territory_name as uf, e.harvest_year as year, round(100 * a.yield_anomaly_pct) as ols_pct, round(100 * t.ts_anomaly_pct) as ts_pct,
       round((100 * (a.trend_yield_kg_ha / (a.yield_kg_ha / (1 + t.ts_anomaly_pct)) - 1))::numeric, 1) as ols_vs_ts_trend_pct
from seeds.known_climate_events e
join marts.agg_climate_yield_association a on a.crop = e.crop and a.territory_level = e.territory_level and a.territory_name = e.territory_name and a.harvest_year = e.harvest_year
join theil_sen t on t.territory_level = a.territory_level and t.territory_id = a.territory_id and t.harvest_year = a.harvest_year
where e.crop = 'soybean' order by 2, 1;

\echo '== soybean immediate regions: median correlation water balance x anomaly, OLS vs Theil-Sen'
with per_region as (
  select a.territory_id, corr(a.water_balance_z, a.yield_anomaly_pct) as c_ols, corr(a.water_balance_z, t.ts_anomaly_pct) as c_ts, count(*) as n
  from marts.agg_climate_yield_association a
  join theil_sen t on t.territory_level = a.territory_level and t.territory_id = a.territory_id and t.harvest_year = a.harvest_year
  where a.crop = 'soybean' and a.territory_level = 'immediate_region' and a.is_normal_available and a.is_trend_available
  group by 1 having count(*) >= 15)
select count(*) as regions, round(percentile_cont(0.5) within group (order by c_ols)::numeric, 3) as median_ols, round(percentile_cont(0.5) within group (order by c_ts)::numeric, 3) as median_ts,
       count(*) filter (where c_ols > 0) as positive_ols, count(*) filter (where c_ts > 0) as positive_ts
from per_region;

-- ---------- Coffee MG: 2x2 moving average vs log-linear with biennial term ----------
\echo '== coffee arabica MG (state): 2x2 MA vs OLS with parity dummy'
with y as (
  select harvest_year, yield_kg_ha, ln(yield_kg_ha) as ly, (harvest_year % 2)::numeric as parity
  from intermediate.int_yield__territory_trend where crop = 'coffee_arabica' and territory_level = 'state' and yield_kg_ha > 0),
-- two-regressor OLS: ly = a + b*year + c*parity, via centered normal equations
stats as (
  select avg(ly) as my, avg(harvest_year) as mx, avg(parity) as mp,
         sum((harvest_year - (select avg(harvest_year) from y))^2) as sxx,
         sum((parity - (select avg(parity) from y))^2) as spp,
         sum((harvest_year - (select avg(harvest_year) from y)) * (parity - (select avg(parity) from y))) as sxp,
         sum((harvest_year - (select avg(harvest_year) from y)) * (ly - (select avg(ly) from y))) as sxy,
         sum((parity - (select avg(parity) from y)) * (ly - (select avg(ly) from y))) as spy
  from y),
coef as (
  select (sxy * spp - spy * sxp) / nullif(sxx * spp - sxp * sxp, 0) as b,
         (spy * sxx - sxy * sxp) / nullif(sxx * spp - sxp * sxp, 0) as c, my, mx, mp from stats)
select y.harvest_year, round(y.yield_kg_ha) as yield,
       round(100 * a.yield_anomaly_pct) as ma2x2_pct,
       round(100 * (y.yield_kg_ha / exp(coef.my + coef.b * (y.harvest_year - coef.mx) + coef.c * (y.parity - coef.mp)) - 1)) as ols_parity_pct,
       round(a.water_balance_z::numeric, 2) as filling_wb_z, round(a.frost_area_share::numeric, 2) as frost_share,
       round(100 * (exp(coef.b) - 1), 2) as trend_growth_pct_yr, round(100 * (exp(coef.c) - 1)) as parity_effect_pct
from y cross join coef
left join marts.agg_climate_yield_association a on a.crop = 'coffee_arabica' and a.territory_level = 'state' and a.harvest_year = y.harvest_year
order by y.harvest_year;
