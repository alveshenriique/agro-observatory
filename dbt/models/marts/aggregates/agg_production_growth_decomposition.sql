-- Log decomposition of production growth into area and yield effects:
--   ln(P1/P0) = ln(A1/A0) + ln(Y1/Y0), with Y = P / A (harvested area).
-- Each period is the 3-year average around an anchor year, to smooth atypical crop years.
-- Grain: crop × territory (Brazil and the 5 macro regions) × period pair.
-- `is_low_base` flags pairs whose start period had less than 1% of the crop's national
-- production: their log growth is correct but huge (the crop practically started from zero).

{% set anchors = [1975, 1985, 1995, 2005, 2015, 2024] %}

with anchors as (
    select anchor_year
    from unnest(array{{ anchors }}) as anchor_year
),

production as (
    select
        fct.crop,
        fct.year,
        dim.region_id,
        dim.region_name,
        fct.production_t,
        fct.harvested_area_ha
    from {{ ref('fct_crop_production') }} as fct
    inner join {{ ref('dim_crop') }} as crop on fct.crop = crop.crop
    inner join {{ ref('dim_municipality') }} as dim on fct.municipality_id = dim.municipality_id
    -- Arabica/canephora only exist from 2012 on; the long series uses coffee_total.
    where not crop.is_coffee_breakdown
),

-- Annual totals per territory. Brazil is region_id 0.
annual as (
    select crop, year, region_id, region_name,
           sum(production_t) as production_t, sum(harvested_area_ha) as harvested_area_ha
    from production
    group by crop, year, region_id, region_name
    union all
    select crop, year, 0, 'Brasil', sum(production_t), sum(harvested_area_ha)
    from production
    group by crop, year
),

-- 3-year averages (anchor - 1 to anchor + 1). Yield is derived from the averages
-- (sum of production / sum of area), never averaged itself.
periods as (
    select
        annual.crop,
        annual.region_id,
        annual.region_name,
        anchors.anchor_year,
        avg(annual.production_t) as production_t,
        avg(annual.harvested_area_ha) as harvested_area_ha,
        count(*) as years_in_window
    from annual
    inner join anchors on annual.year between anchors.anchor_year - 1 and anchors.anchor_year + 1
    group by 1, 2, 3, 4
),

periods_with_share as (
    select
        *,
        production_t / nullif(
            max(case when region_id = 0 then production_t end)
                over (partition by crop, anchor_year),
            0
        ) as share_of_national_production
    from periods
),

pairs as (
    -- Consecutive periods plus the full span.
    select a0.anchor_year as start_anchor, a1.anchor_year as end_anchor
    from anchors as a0
    inner join anchors as a1
        on a1.anchor_year = (select min(anchor_year) from anchors where anchor_year > a0.anchor_year)
    union all
    select min(anchor_year), max(anchor_year) from anchors
),

compared as (
    select
        p0.crop,
        p0.region_id,
        p0.region_name,
        pairs.start_anchor,
        pairs.end_anchor,
        p0.production_t as start_production_t,
        p1.production_t as end_production_t,
        p0.harvested_area_ha as start_harvested_area_ha,
        p1.harvested_area_ha as end_harvested_area_ha,
        p0.share_of_national_production as start_share_of_national_production,
        p0.production_t / nullif(p0.harvested_area_ha, 0) as start_yield_t_ha,
        p1.production_t / nullif(p1.harvested_area_ha, 0) as end_yield_t_ha
    from pairs
    inner join periods_with_share as p0 on p0.anchor_year = pairs.start_anchor
    inner join periods_with_share as p1
        on p1.anchor_year = pairs.end_anchor
        and p1.crop = p0.crop
        and p1.region_id = p0.region_id
    where p0.years_in_window = 3 and p1.years_in_window = 3
),

logs as (
    select
        *,
        -- Undefined (null) when a period has no production or area (e.g. soy in the North in 1975).
        case when start_production_t > 0 and end_production_t > 0
            then ln(end_production_t / start_production_t) end as ln_production_growth,
        case when start_harvested_area_ha > 0 and end_harvested_area_ha > 0
            then ln(end_harvested_area_ha / start_harvested_area_ha) end as ln_area_effect,
        case when start_yield_t_ha > 0 and end_yield_t_ha > 0
            then ln(end_yield_t_ha / start_yield_t_ha) end as ln_yield_effect
    from compared
)

select
    crop,
    case when region_id = 0 then 'country' else 'macro_region' end as territory_level,
    region_id as territory_id,
    region_name as territory_name,
    start_anchor,
    end_anchor,
    (start_anchor - 1)::text || '-' || (start_anchor + 1)::text as start_period,
    (end_anchor - 1)::text || '-' || (end_anchor + 1)::text as end_period,
    start_production_t,
    end_production_t,
    start_harvested_area_ha,
    end_harvested_area_ha,
    start_share_of_national_production,
    coalesce(start_share_of_national_production < {{ var('low_base_share_threshold') }}, true)
        as is_low_base,
    start_yield_t_ha * 1000 as start_yield_kg_ha,
    end_yield_t_ha * 1000 as end_yield_kg_ha,
    ln_production_growth,
    ln_area_effect,
    ln_yield_effect,
    -- Share of log growth explained by area (the rest is yield). Can fall outside [0, 1]
    -- when one effect is negative.
    ln_area_effect / nullif(ln_production_growth, 0) as area_share_of_growth,
    ln_yield_effect / nullif(ln_production_growth, 0) as yield_share_of_growth
from logs
