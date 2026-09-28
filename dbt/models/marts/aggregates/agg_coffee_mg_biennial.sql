-- Coffee production in Minas Gerais, to identify the biennial (on/off year) cycle of arabica.
-- Two series: coffee_arabica (from 2012) and coffee_total (long series, a proxy for arabica
-- since most of MG's coffee is arabica).
-- The trend is a centered 2x2 moving average (weights 1/4, 1/2, 1/4), which removes a
-- 2-year cycle exactly; production / trend > 1 marks an on year, < 1 an off year.
-- Grain: crop × year.

with mg as (
    select fct.crop, fct.year, sum(fct.production_t) as production_t
    from {{ ref('fct_crop_production') }} as fct
    inner join {{ ref('dim_municipality') }} as dim on fct.municipality_id = dim.municipality_id
    where dim.state_abbreviation = 'MG'
        and fct.crop in ('coffee_arabica', 'coffee_total')
    group by fct.crop, fct.year
),

windowed as (
    select
        *,
        lag(production_t) over (partition by crop order by year) as previous_production_t,
        lead(production_t) over (partition by crop order by year) as next_production_t
    from mg
),

trend as (
    select
        *,
        0.25 * previous_production_t + 0.5 * production_t + 0.25 * next_production_t
            as centered_trend_t
    from windowed
)

select
    crop,
    year,
    production_t,
    production_t / nullif(previous_production_t, 0) - 1 as change_vs_previous_year,
    centered_trend_t,
    production_t / nullif(centered_trend_t, 0) as ratio_to_trend,
    case
        when centered_trend_t is null then null
        when production_t > centered_trend_t then 'on_year'
        else 'off_year'
    end as cycle_phase
from trend
