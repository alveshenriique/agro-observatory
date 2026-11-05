-- Yield (sum of production / sum of harvested area) by territory × crop × harvest year, its
-- technological trend and the detrended anomaly. Territory levels: immediate region and
-- state. Municipalities are too noisy and change with splits, so no trend is fitted there.
--
-- Trend methods:
-- - log-linear OLS per territory over `yield_trend_start_year`-`yield_trend_end_year`
--   (constant percentage gain per year, slope = covar_pop / var_pop), fitted on years with at least
--   `yield_trend_min_harvested_area_ha` and requiring `yield_trend_min_years` of them.
--   Drought years pull the line down a little (see docs/VALIDACAO.md; Theil-Sen is the robust option);
-- - for biennial crops (`biennial_crops`), the centered 2x2 moving average of yield, which
--   removes the two-year cycle and the slow trend together; null at the series edges. It
--   absorbs shocks that last two years (2014-2015, 2021-2022 in MG), so a second estimate is
--   given alongside (`biennial_ols_*`): a log-linear OLS fit with a parity term (odd/even
--   year), which keeps those shocks visible but assumes the on/off alternation never flips.
--   Neither is adequate alone; the marts carry both.
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
        fct.planted_or_bearing_area_ha,
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
        cast({{ name_column }} as {{ dbt.type_string() }}) as territory_name,
        crop,
        harvest_year,
        sum(production_t) as production_t,
        sum(planted_or_bearing_area_ha) as planted_or_bearing_area_ha,
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

-- OLS slope as covar_pop / var_pop (regr_slope is not available in every dialect); the line
-- is then evaluated in centered form: mean(ln y) + slope * (year - mean(year)).
log_linear_fit as (
    select
        territory_level,
        territory_id,
        crop,
        covar_pop(ln(yield_kg_ha), harvest_year) / nullif(var_pop(harvest_year), 0) as slope,
        avg(ln(yield_kg_ha)) as mean_log_yield,
        avg(harvest_year) as mean_year,
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

-- Two-regressor OLS ln(y) = a + b * year + c * parity, solved from the population
-- covariances (the row count cancels), so it is one aggregation pass and portable.
biennial_fit as (
    select
        territory_level,
        territory_id,
        crop,
        count(*) as n_years,
        avg(ln(yield_kg_ha)) as mean_log_yield,
        avg(harvest_year) as mean_year,
        avg(mod(harvest_year, 2)) as mean_parity,
        covar_pop(harvest_year, ln(yield_kg_ha)) as cov_year_log_yield,
        covar_pop(mod(harvest_year, 2), ln(yield_kg_ha)) as cov_parity_log_yield,
        covar_pop(harvest_year, mod(harvest_year, 2)) as cov_year_parity,
        var_pop(harvest_year) as var_year,
        var_pop(mod(harvest_year, 2)) as var_parity
    from eligible
    where crop in ({{ "'" ~ biennial | join("', '") ~ "'" }}) and is_eligible
    group by territory_level, territory_id, crop
),

biennial_coefficients as (
    select
        *,
        (cov_year_log_yield * var_parity - cov_parity_log_yield * cov_year_parity)
            / nullif(var_year * var_parity - cov_year_parity * cov_year_parity, 0) as slope,
        (cov_parity_log_yield * var_year - cov_year_log_yield * cov_year_parity)
            / nullif(var_year * var_parity - cov_year_parity * cov_year_parity, 0) as parity_effect
    from biennial_fit
),

with_trend as (
    select
        eligible.*,
        case
            when ols.n_years >= {{ var('biennial_ols_min_years') }} and eligible.is_eligible
                then exp(
                    ols.mean_log_yield
                    + ols.slope * (eligible.harvest_year - ols.mean_year)
                    + ols.parity_effect * (mod(eligible.harvest_year, 2) - ols.mean_parity)
                )
        end as biennial_ols_trend_yield_kg_ha,
        ols.n_years as biennial_ols_n_years,
        exp(ols.slope) - 1 as biennial_ols_annual_growth_pct,
        exp(ols.parity_effect) - 1 as biennial_ols_parity_effect_pct,
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
                then exp(fit.mean_log_yield + fit.slope * (eligible.harvest_year - fit.mean_year))
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
    left join biennial_coefficients as ols
        on ols.territory_level = eligible.territory_level
        and ols.territory_id = eligible.territory_id
        and ols.crop = eligible.crop
)

select
    territory_level,
    territory_id,
    territory_name,
    crop,
    harvest_year,
    production_t,
    planted_or_bearing_area_ha,
    harvested_area_ha,
    yield_kg_ha,
    trend_method,
    trend_n_years,
    annual_trend_growth_pct,
    trend_yield_kg_ha,
    trend_yield_kg_ha is not null as is_trend_available,
    yield_kg_ha / nullif(trend_yield_kg_ha, 0) - 1 as yield_anomaly_pct,
    -- Biennial crops only: the alternative detrending (OLS with parity term).
    biennial_ols_trend_yield_kg_ha,
    biennial_ols_trend_yield_kg_ha is not null as is_biennial_ols_available,
    yield_kg_ha / nullif(biennial_ols_trend_yield_kg_ha, 0) - 1 as biennial_ols_yield_anomaly_pct,
    biennial_ols_n_years,
    biennial_ols_annual_growth_pct,
    -- Yield in odd years relative to even years, as a fraction (e.g. -0.08 = 8% lower).
    biennial_ols_parity_effect_pct
from with_trend
