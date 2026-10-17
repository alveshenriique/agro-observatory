-- Yield (sum of production / sum of harvested area) by territory × crop × harvest year, its
-- technological trend and the detrended anomaly. Territory levels: immediate region and
-- state. Municipalities are too noisy and change with splits, so no trend is fitted there.
--
-- Trend methods:
-- - log-linear OLS per territory over `yield_trend_start_year`-`yield_trend_end_year`
--   (constant percentage gain per year), fitted on years with at least
--   `yield_trend_min_harvested_area_ha` and requiring `yield_trend_min_years` of them.
--   Drought years pull the line down a little (see README; Theil-Sen is the robust option);
-- - for biennial crops (`biennial_crops`), the centered 2x2 moving average of yield, which
--   removes the two-year cycle and the slow trend together; null at the series edges.
{{ config(materialized='table') }}

{% set levels = [
    ('immediate_region', 'immediate_region_id', 'immediate_region_name'),
    ('state', 'state_id', 'state_abbreviation'),
] %}
{% set biennial = var('biennial_crops') %}

with base as (
    select
        fct.crop,
        fct.year as harvest_year,
        fct.production_t,
        fct.planted_area_ha,
        fct.harvested_area_ha,
        dim.immediate_region_id,
        dim.immediate_region_name,
        dim.state_id,
        dim.state_abbreviation
    from {{ ref('fct_crop_production') }} as fct
    inner join {{ ref('dim_municipality') }} as dim
        on fct.municipality_id = dim.municipality_id
    inner join {{ ref('int_climate__producing_municipalities') }} as producing
        on producing.municipality_id = fct.municipality_id
        and producing.crop = fct.crop
    where fct.production_t > 0
),

territory_years as (
    {% for level, id_column, name_column in levels %}
    select
        '{{ level }}' as territory_level,
        {{ id_column }} as territory_id,
        {{ name_column }}::text as territory_name,
        crop,
        harvest_year,
        sum(production_t) as production_t,
        sum(planted_area_ha) as planted_area_ha,
        sum(harvested_area_ha) as harvested_area_ha,
        sum(production_t) / nullif(sum(harvested_area_ha), 0) * 1000 as yield_kg_ha
    from base
    group by 1, 2, 3, 4, 5
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
),

eligible as (
    select
        *,
        harvested_area_ha >= {{ var('yield_trend_min_harvested_area_ha') }}
            and yield_kg_ha > 0 as is_eligible
    from territory_years
),

log_linear_fit as (
    select
        territory_level,
        territory_id,
        crop,
        regr_slope(ln(yield_kg_ha), harvest_year) as slope,
        regr_intercept(ln(yield_kg_ha), harvest_year) as intercept,
        count(*) as n_years
    from eligible
    where crop not in ({{ "'" ~ biennial | join("', '") ~ "'" }})
        and is_eligible
        and harvest_year between {{ var('yield_trend_start_year') }} and {{ var('yield_trend_end_year') }}
    group by territory_level, territory_id, crop
),

moving_average as (
    select
        territory_level,
        territory_id,
        crop,
        harvest_year,
        lag(harvest_year) over w as previous_year,
        lead(harvest_year) over w as next_year,
        0.25 * lag(yield_kg_ha) over w + 0.5 * yield_kg_ha + 0.25 * lead(yield_kg_ha) over w
            as centered_trend
    from eligible
    where crop in ({{ "'" ~ biennial | join("', '") ~ "'" }}) and is_eligible
    window w as (partition by territory_level, territory_id, crop order by harvest_year)
),

with_trend as (
    select
        eligible.*,
        case
            when eligible.crop in ({{ "'" ~ biennial | join("', '") ~ "'" }})
                then 'centered_2x2_moving_average'
            else 'log_linear_ols'
        end as trend_method,
        fit.n_years as trend_n_years,
        exp(fit.slope) - 1 as annual_trend_growth_pct,
        case
            when eligible.crop in ({{ "'" ~ biennial | join("', '") ~ "'" }}) then
                case
                    when ma.previous_year = eligible.harvest_year - 1
                        and ma.next_year = eligible.harvest_year + 1
                        then ma.centered_trend
                end
            when fit.n_years >= {{ var('yield_trend_min_years') }}
                and eligible.is_eligible
                and eligible.harvest_year
                    between {{ var('yield_trend_start_year') }} and {{ var('yield_trend_end_year') }}
                then exp(fit.intercept + fit.slope * eligible.harvest_year)
        end as trend_yield_kg_ha
    from eligible
    left join log_linear_fit as fit
        on fit.territory_level = eligible.territory_level
        and fit.territory_id = eligible.territory_id
        and fit.crop = eligible.crop
    left join moving_average as ma
        on ma.territory_level = eligible.territory_level
        and ma.territory_id = eligible.territory_id
        and ma.crop = eligible.crop
        and ma.harvest_year = eligible.harvest_year
)

select
    territory_level,
    territory_id,
    territory_name,
    crop,
    harvest_year,
    production_t,
    planted_area_ha,
    harvested_area_ha,
    yield_kg_ha,
    trend_method,
    trend_n_years,
    annual_trend_growth_pct,
    trend_yield_kg_ha,
    trend_yield_kg_ha is not null as is_trend_available,
    yield_kg_ha / nullif(trend_yield_kg_ha, 0) - 1 as yield_anomaly_pct
from with_trend
