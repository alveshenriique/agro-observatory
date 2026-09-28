-- Share of national production by state and by intermediate region, per crop and year.
-- Stable territorial levels are used instead of municipalities, which split over time.
-- The grid is complete (every territory in every year, 0 when it produced nothing), so
-- threshold crossings are not missed in years without rows.
-- Grain: crop × territory level × territory × year.

with crops as (
    select crop from {{ ref('dim_crop') }} where not is_coffee_breakdown
),

years as (
    select year from {{ ref('dim_year') }}
),

territories as (
    select distinct 'state' as territory_level, state_id as territory_id,
           state_abbreviation as territory_name
    from {{ ref('dim_municipality') }}
    union all
    select distinct 'intermediate_region', intermediate_region_id,
           intermediate_region_name || ' (' || state_abbreviation || ')'
    from {{ ref('dim_municipality') }}
),

production as (
    select fct.crop, fct.year, dim.state_id, dim.intermediate_region_id, fct.production_t
    from {{ ref('fct_crop_production') }} as fct
    inner join crops on fct.crop = crops.crop
    inner join {{ ref('dim_municipality') }} as dim on fct.municipality_id = dim.municipality_id
),

by_territory as (
    select crop, year, 'state' as territory_level, state_id as territory_id,
           sum(production_t) as production_t
    from production
    group by 1, 2, 3, 4
    union all
    select crop, year, 'intermediate_region', intermediate_region_id, sum(production_t)
    from production
    group by 1, 2, 3, 4
),

grid as (
    select
        crops.crop,
        years.year,
        territories.territory_level,
        territories.territory_id,
        territories.territory_name,
        coalesce(by_territory.production_t, 0) as production_t
    from crops
    cross join years
    cross join territories
    left join by_territory
        on by_territory.crop = crops.crop
        and by_territory.year = years.year
        and by_territory.territory_level = territories.territory_level
        and by_territory.territory_id = territories.territory_id
)

select
    *,
    sum(production_t) over (partition by crop, year, territory_level) as national_production_t,
    production_t
        / nullif(sum(production_t) over (partition by crop, year, territory_level), 0)
        as share_of_national_production
from grid
