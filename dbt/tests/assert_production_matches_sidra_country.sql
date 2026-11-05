-- External validation: the project's sums over municipalities must reproduce the Brazil
-- aggregates IBGE publishes for the same table (SIDRA 5457, level N1), for production,
-- harvested area, planted area and yield (ratio of sums, within 1 kg/ha of rounding).
-- Runs only on the full data (the CI sample has 7 municipalities). Cells where IBGE's own
-- national total differs from the sum of its municipal rows are listed in
-- sidra_known_discrepancies.
with ours as (
    select
        crop,
        year,
        sum(production_t) as production_t,
        sum(harvested_area_ha) as harvested_area_ha,
        sum(planted_or_bearing_area_ha) as planted_area_ha,
        sum(production_t) / nullif(sum(harvested_area_ha), 0) * 1000 as yield_kg_ha
    from {{ ref('fct_crop_production') }}
    group by crop, year
),

official as (
    select crop, year, variable, official_value
    from {{ ref('sidra_official_aggregates') }}
    where territory_level = 'country' and official_value is not null
),

known as (
    select territory_level, crop, year, variable
    from {{ ref('sidra_known_discrepancies') }}
    where territory_level = 'country'
),

compared as (
    select
        official.crop,
        official.year,
        official.variable,
        official.official_value,
        case official.variable
            when 'production_t' then ours.production_t
            when 'harvested_area_ha' then ours.harvested_area_ha
            when 'planted_area_ha' then ours.planted_area_ha
            when 'yield_kg_ha' then ours.yield_kg_ha
        end as our_value,
        case when official.variable = 'yield_kg_ha' then 1 else 0.5 end as tolerance
    from official
    left join ours on ours.crop = official.crop and ours.year = official.year
    left join known
        on known.crop = official.crop and known.year = official.year and known.variable = official.variable
    where known.crop is null
)

select *, our_value - official_value as difference
from compared
where (select count(distinct municipality_id) from {{ ref('fct_crop_production') }}) >= 5000
    and abs(coalesce(our_value, 0) - official_value) > tolerance
