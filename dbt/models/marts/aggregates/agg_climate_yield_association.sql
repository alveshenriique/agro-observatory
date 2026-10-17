-- Climate anomalies and detrended yield anomaly by territory × crop × harvest year, to ask
-- whether years with water deficit, heat or frost in the critical window had below-trend
-- yields. Association only: no causal claim.
--
-- Municipal climate anomalies (z-scores against each municipality's own normal) are averaged
-- with planted-area weights: the planted area is decided before the season's weather, so it
-- is not affected by the shock (part of it is simply not harvested in a drought). Planted
-- area only exists from `planted_area_first_year` (1988); earlier years fall back to
-- harvested area, flagged in `weight_basis`.
-- The primary window is `critical` for soybean and `filling` for arabica coffee; soybean also
-- carries the whole-season water balance (`season_*`), because a deficit at planting shows up
-- there and not in the critical window (e.g. MATOPIBA in 2016).
{% set levels = [
    ('immediate_region', 'immediate_region_id', 'immediate_region_name'),
    ('state', 'state_id', 'state_abbreviation'),
] %}
{% set weighted_means = [
    'water_balance_z', 'precipitation_pct_of_normal', 'hot_days_z', 'longest_dry_spell_z',
    'season_water_balance_z', 'flowering_water_balance_z', 'frost_tmin_min_c', 'frost_tmin_min_z',
] %}
{% set z = var('stress_z_threshold') %}

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
            when climate.harvest_year >= {{ var('planted_area_first_year') }} then production.planted_area_ha
            else production.harvested_area_ha
        end as weight,
        case when climate.crop = 'coffee_arabica' then 'filling' else 'critical' end as primary_window,
        case when climate.crop = 'coffee_arabica' then climate.filling_water_balance_z else climate.critical_water_balance_z end as water_balance_z,
        case when climate.crop = 'coffee_arabica' then climate.filling_precipitation_pct_of_normal else climate.critical_precipitation_pct_of_normal end as precipitation_pct_of_normal,
        case when climate.crop = 'coffee_arabica' then climate.filling_hot_days_z else climate.critical_hot_days_z end as hot_days_z,
        case when climate.crop = 'coffee_arabica' then climate.filling_longest_dry_spell_z else climate.critical_longest_dry_spell_z end as longest_dry_spell_z,
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
        {{ name_column }}::text as territory_name,
        crop,
        harvest_year,
        max(primary_window) as primary_window,
        count(*) as municipalities,
        sum(weight) as total_weight,
        sum(weight) filter (where water_balance_z is not null) as weight_with_normal,
        {% for column in weighted_means %}
        sum(weight * {{ column }}) filter (where {{ column }} is not null)
            / nullif(sum(weight) filter (where {{ column }} is not null), 0) as {{ column }},
        {% endfor %}
        sum(weight) filter (where frost_days >= 1)
            / nullif(sum(weight) filter (where frost_days is not null), 0) as frost_area_share
    from municipal
    where weight is not null
    group by 1, 2, 3, 4, 5
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
),

with_flags as (
    select
        *,
        case
            when harvest_year >= {{ var('planted_area_first_year') }} then 'planted_area'
            else 'harvested_area'
        end as weight_basis,
        coalesce(weight_with_normal / nullif(total_weight, 0), 0) >= 0.5 as is_normal_available
    from by_territory
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
    territory.is_normal_available,
    {% for column in weighted_means %}
    case when territory.is_normal_available then territory.{{ column }} end as {{ column }},
    {% endfor %}
    case when territory.crop = 'coffee_arabica' then territory.frost_area_share end as frost_area_share,
    case when territory.is_normal_available then territory.water_balance_z <= -{{ z }} end as is_water_deficit,
    case when territory.is_normal_available then territory.hot_days_z >= {{ z }} end as is_heat_stress,
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
    trend.yield_anomaly_pct
from with_flags as territory
left join {{ ref('int_yield__territory_trend') }} as trend
    on trend.territory_level = territory.territory_level
    and trend.territory_id = territory.territory_id
    and trend.crop = territory.crop
    and trend.harvest_year = territory.harvest_year
