-- External validation at the state level (SIDRA 5457, level N3): the project's sums over
-- municipalities must reproduce the state aggregates IBGE publishes. Runs only on the full
-- data (the CI sample has 7 municipalities).
--
-- IBGE publishes the historical state series with the territory of each year: before the
-- splits, "Mato Grosso" includes today's Mato Grosso do Sul (until 1978) and "Goiás"
-- includes Tocantins (until 1988). The project uses the current mesh, so those years are
-- compared on the merged territories. Cells where IBGE's own state total differs from the
-- sum of its municipal rows (1974 RJ, 1998, 2002, 2010-2011) are listed in
-- sidra_known_discrepancies.
with municipal as (
    select
        fct.crop,
        fct.year,
        case
            when fct.year <= 1978 and dim.state_id in (50, 51) then 51  -- MT + MS -> Mato Grosso
            when fct.year <= 1988 and dim.state_id in (52, 17) then 52  -- GO + TO -> Goiás
            else dim.state_id
        end as state_id,
        fct.production_t,
        fct.harvested_area_ha,
        fct.planted_or_bearing_area_ha as planted_area_ha
    from {{ ref('fct_crop_production') }} as fct
    inner join {{ ref('dim_municipality') }} as dim on dim.municipality_id = fct.municipality_id
),

ours as (
    select
        state_id,
        crop,
        year,
        sum(production_t) as production_t,
        sum(harvested_area_ha) as harvested_area_ha,
        sum(planted_area_ha) as planted_area_ha,
        sum(production_t) / nullif(sum(harvested_area_ha), 0) * 1000 as yield_kg_ha
    from municipal
    group by state_id, crop, year
),

official as (
    select territory_id as state_id, territory_name, crop, year, variable, official_value
    from {{ ref('sidra_official_aggregates') }}
    where territory_level = 'state' and official_value is not null
),

known as (
    select territory_level, territory_id, crop, year, variable
    from {{ ref('sidra_known_discrepancies') }}
),

compared as (
    select
        official.state_id,
        official.territory_name,
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
    left join ours
        on ours.state_id = official.state_id and ours.crop = official.crop and ours.year = official.year
    left join known
        on known.territory_level = 'state' and known.territory_id = official.state_id
        and known.crop = official.crop and known.year = official.year and known.variable = official.variable
    where known.territory_id is null
)

select *, our_value - official_value as difference
from compared
where (select count(distinct municipality_id) from {{ ref('fct_crop_production') }}) >= 5000
    and abs(coalesce(our_value, 0) - official_value) > tolerance
