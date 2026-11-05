-- Climate anomalies and detrended yield anomaly by territory × crop × harvest year, to ask
-- whether years with water deficit, heat or frost in the critical window had below-trend
-- yields. Association only: no causal claim.
--
-- Municipal climate anomalies (z-scores against each municipality's own normal) are averaged
-- with planted-area weights: the planted area is decided before the season's weather, so it
-- is not affected by the shock (part of it is simply not harvested in a drought). For coffee,
-- a permanent crop, the same PAM variable is the bearing area (area destined for harvest).
-- Planted area only exists from `planted_area_first_year` (1988); earlier years fall back to
-- harvested area, flagged in `weight_basis`.
-- A mean of municipal z-scores is not itself a z-score: its spread shrinks when the
-- municipalities do not move together (sd 0.96 in immediate regions, 0.86 in states), so a
-- cut at z = -1 would flag fewer years in large territories. Each territory's weighted-mean
-- series is therefore standardized again against its own 1991-2020 mean and standard
-- deviation (`*_z`; the plain means stay in `*_z_municipal_mean`), when it has at least
-- `territory_normal_min_years` years in that period. Territories without that history (arabica
-- coffee only exists from 2012) keep the plain mean, flagged by `is_territory_standardized`.
-- Rain relative to the normal is a ratio of weighted sums (rain / normal rain), not a mean
-- of municipal ratios. Heat stress needs both a high z-score of hot days and at least
-- `heat_min_extra_hot_days` days above the normal, because the z alone explodes where the
-- normal spread is near zero.
-- The primary window is `critical` for soybean and `filling` for arabica coffee; soybean also
-- carries the whole-season water balance (`season_*`), because a deficit at planting shows up
-- there and not in the critical window (e.g. MATOPIBA in 2016).
{% set levels = [
    ('immediate_region', 'immediate_region_id', 'immediate_region_name'),
    ('state', 'state_id', 'state_abbreviation'),
] %}
{% set z_columns = [
    'water_balance_z', 'hot_days_z', 'heat_degree_days_z', 'longest_dry_spell_z',
    'season_water_balance_z', 'flowering_water_balance_z', 'frost_tmin_min_z',
] %}
{% set plain_means = ['hot_days_anomaly_days', 'frost_tmin_min_c'] %}
{% set z = var('stress_z_threshold') %}
{% set min_ref_years = var('territory_normal_min_years') %}

with climate as (
    select * from {{ ref('fct_crop_climate') }}
),

municipal as (
    select
        climate.municipality_id,
        climate.crop,
        climate.harvest_year,
        dim.immediate_region_id,
        dim.immediate_region_name,
        dim.state_id,
        dim.state_abbreviation,
        case
            when climate.harvest_year >= {{ var('planted_area_first_year') }}
                then production.planted_or_bearing_area_ha
            else production.harvested_area_ha
        end as weight,
        case when climate.crop = 'coffee_arabica' then 'filling' else 'critical' end as primary_window,
        {% for column in ['water_balance_z', 'hot_days_z', 'heat_degree_days_z', 'longest_dry_spell_z',
                          'precipitation_mm', 'precipitation_normal_mm', 'hot_days_anomaly_days'] %}
        case
            when climate.crop = 'coffee_arabica' then climate.filling_{{ column }}
            else climate.critical_{{ column }}
        end as {{ column }},
        {% endfor %}
        climate.season_water_balance_z,
        climate.flowering_water_balance_z,
        climate.frost_days,
        climate.frost_tmin_min_c,
        climate.frost_tmin_min_z
    from climate
    inner join {{ ref('fct_crop_production') }} as production
        on production.municipality_id = climate.municipality_id
        and production.crop = climate.crop
        and production.year = climate.harvest_year
    inner join {{ ref('dim_municipality') }} as dim
        on dim.municipality_id = climate.municipality_id
),

by_territory as (
    {% for level, id_column, name_column in levels %}
    select
        '{{ level }}' as territory_level,
        {{ id_column }} as territory_id,
        cast({{ name_column }} as {{ dbt.type_string() }}) as territory_name,
        crop,
        harvest_year,
        max(primary_window) as primary_window,
        count(*) as municipalities,
        sum(weight) as total_weight,
        sum(case when water_balance_z is not null then weight end) as weight_with_normal,
        {% for column in z_columns %}
        sum(case when {{ column }} is not null then weight * {{ column }} end)
            / nullif(sum(case when {{ column }} is not null then weight end), 0) as {{ column }}_municipal_mean,
        {% endfor %}
        {% for column in plain_means %}
        sum(case when {{ column }} is not null then weight * {{ column }} end)
            / nullif(sum(case when {{ column }} is not null then weight end), 0) as {{ column }},
        {% endfor %}
        -- Ratio of weighted sums: territory rain over territory normal rain, in %.
        sum(case when precipitation_mm is not null and precipitation_normal_mm is not null
                then weight * precipitation_mm end)
            / nullif(sum(case when precipitation_mm is not null and precipitation_normal_mm is not null
                then weight * precipitation_normal_mm end), 0) * 100 as precipitation_pct_of_normal,
        sum(case when frost_days >= 1 then weight end)
            / nullif(sum(case when frost_days is not null then weight end), 0) as frost_area_share
    from municipal
    where weight is not null
    group by 1, 2, 3, 4, 5
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
),

with_coverage as (
    select
        *,
        coalesce(weight_with_normal / nullif(total_weight, 0), 0) >= 0.5 as is_municipal_normal_available
    from by_territory
),

-- Each territory's own normal: mean and spread of its weighted-mean series over the
-- reference period, used to standardize the series again.
territory_normal as (
    select
        territory_level,
        territory_id,
        crop,
        {% for column in z_columns %}
        avg({{ column }}_municipal_mean) as {{ column }}_ref_mean,
        stddev_samp({{ column }}_municipal_mean) as {{ column }}_ref_sd,
        count({{ column }}_municipal_mean) as {{ column }}_ref_years{{ "," if not loop.last }}
        {% endfor %}
    from with_coverage
    where is_municipal_normal_available
        and harvest_year between {{ var('climate_normal_start_year') }} and {{ var('climate_normal_end_year') }}
    group by territory_level, territory_id, crop
),

standardized as (
    select
        territory.*,
        {% for column in z_columns %}
        case
            when normal.{{ column }}_ref_years >= {{ min_ref_years }}
                then (territory.{{ column }}_municipal_mean - normal.{{ column }}_ref_mean)
                    / nullif(normal.{{ column }}_ref_sd, 0)
            else territory.{{ column }}_municipal_mean
        end as {{ column }},
        {% endfor %}
        coalesce(normal.water_balance_z_ref_years, 0) as territory_normal_years,
        coalesce(normal.water_balance_z_ref_years, 0) >= {{ min_ref_years }} as is_territory_standardized,
        case
            when territory.harvest_year >= {{ var('planted_area_first_year') }} then 'planted_or_bearing_area'
            else 'harvested_area'
        end as weight_basis,
        territory.is_municipal_normal_available as is_normal_available
    from with_coverage as territory
    left join territory_normal as normal
        on normal.territory_level = territory.territory_level
        and normal.territory_id = territory.territory_id
        and normal.crop = territory.crop
)

select
    territory.territory_level,
    territory.territory_id,
    territory.territory_name,
    territory.crop,
    territory.harvest_year,
    territory.primary_window,
    territory.municipalities,
    territory.total_weight,
    territory.weight_basis,
    territory.territory_normal_years,
    territory.is_territory_standardized,
    territory.is_normal_available,
    {% for column in z_columns %}
    case when territory.is_normal_available then territory.{{ column }} end as {{ column }},
    case when territory.is_normal_available then territory.{{ column }}_municipal_mean end as {{ column }}_municipal_mean,
    {% endfor %}
    case when territory.is_normal_available then territory.precipitation_pct_of_normal end as precipitation_pct_of_normal,
    case when territory.is_normal_available then territory.hot_days_anomaly_days end as hot_days_anomaly_days,
    case when territory.is_normal_available then territory.frost_tmin_min_c end as frost_tmin_min_c,
    case when territory.crop = 'coffee_arabica' then territory.frost_area_share end as frost_area_share,
    case when territory.is_normal_available then territory.water_balance_z <= -{{ z }} end as is_water_deficit,
    case
        when territory.is_normal_available
            then territory.hot_days_z >= {{ z }}
                and territory.hot_days_anomaly_days >= {{ var('heat_min_extra_hot_days') }}
    end as is_heat_stress,
    -- Soybean only: deficit over the whole season (planting to harvest), a secondary signal.
    case when territory.is_normal_available then territory.season_water_balance_z <= -{{ z }} end as is_season_water_deficit,
    case
        when territory.crop = 'coffee_arabica' and territory.is_normal_available
            then territory.frost_area_share >= {{ var('frost_area_share_threshold') }}
    end as is_frost,
    trend.yield_kg_ha,
    trend.trend_yield_kg_ha,
    trend.trend_method,
    coalesce(trend.is_trend_available, false) as is_trend_available,
    trend.yield_anomaly_pct,
    -- Biennial crops: the alternative detrending (log-linear OLS with a parity term) side by
    -- side with the 2x2 moving average in yield_anomaly_pct.
    coalesce(trend.is_biennial_ols_available, false) as is_biennial_ols_available,
    trend.biennial_ols_yield_anomaly_pct
from standardized as territory
left join {{ ref('int_yield__territory_trend') }} as trend
    on trend.territory_level = territory.territory_level
    and trend.territory_id = territory.territory_id
    and trend.crop = territory.crop
    and trend.harvest_year = territory.harvest_year
