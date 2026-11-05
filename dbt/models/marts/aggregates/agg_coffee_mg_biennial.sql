-- Coffee in Minas Gerais, to identify the biennial (on/off year) cycle of arabica, in
-- production and in yield (production / harvested area). Three series, never mixed:
-- coffee_total_in_husk (1974-2001, measured in husk), coffee_total_processed (2002 on) and
-- coffee_arabica (2012 on, processed). The PAM changed the coffee unit in 2002
-- (`dim_crop.series_break_year`) without a conversion factor, so no ratio or change crosses
-- that year: the moving averages are computed within each series and are null at its edges.
-- coffee_total is a proxy for arabica (MG grows almost only arabica).
-- The trend is a centered 2x2 moving average (weights 1/4, 1/2, 1/4), which removes a 2-year
-- cycle exactly; value / trend > 1 marks an on year, < 1 an off year.
-- Grain: series × year.

with mg as (
    select
        fct.crop,
        case
            when fct.crop = 'coffee_arabica' then 'coffee_arabica'
            when fct.year < crop.series_break_year then 'coffee_total_in_husk'
            else 'coffee_total_processed'
        end as series,
        fct.year,
        year_dim.coffee_production_unit as production_unit,
        sum(fct.production_t) as production_t,
        sum(fct.harvested_area_ha) as harvested_area_ha
    from {{ ref('fct_crop_production') }} as fct
    inner join {{ ref('dim_municipality') }} as dim on fct.municipality_id = dim.municipality_id
    inner join {{ ref('dim_crop') }} as crop on fct.crop = crop.crop
    inner join {{ ref('dim_year') }} as year_dim on fct.year = year_dim.year
    where dim.state_abbreviation = 'MG'
        and fct.crop in ('coffee_arabica', 'coffee_total')
    group by 1, 2, 3, 4
),

with_yield as (
    select
        *,
        production_t * 1000 / nullif(harvested_area_ha, 0) as yield_kg_ha
    from mg
),

windowed as (
    select
        *,
        lag(production_t) over w as previous_production_t,
        lead(production_t) over w as next_production_t,
        lag(yield_kg_ha) over w as previous_yield_kg_ha,
        lead(yield_kg_ha) over w as next_yield_kg_ha
    from with_yield
    window w as (partition by series order by year)
),

trend as (
    select
        *,
        0.25 * previous_production_t + 0.5 * production_t + 0.25 * next_production_t
            as production_centered_trend_t,
        0.25 * previous_yield_kg_ha + 0.5 * yield_kg_ha + 0.25 * next_yield_kg_ha
            as yield_centered_trend_kg_ha
    from windowed
)

select
    series,
    crop,
    year,
    production_unit,
    production_t,
    harvested_area_ha,
    yield_kg_ha,
    production_t / nullif(previous_production_t, 0) - 1 as production_change_vs_previous_year,
    production_centered_trend_t,
    production_t / nullif(production_centered_trend_t, 0) as production_ratio_to_trend,
    yield_centered_trend_kg_ha,
    yield_kg_ha / nullif(yield_centered_trend_kg_ha, 0) as yield_ratio_to_trend,
    case
        when production_centered_trend_t is null then null
        when production_t > production_centered_trend_t then 'on_year'
        else 'off_year'
    end as cycle_phase,
    case
        when yield_centered_trend_kg_ha is null then null
        when yield_kg_ha > yield_centered_trend_kg_ha then 'on_year'
        else 'off_year'
    end as yield_cycle_phase
from trend
