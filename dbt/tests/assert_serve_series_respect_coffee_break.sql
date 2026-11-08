-- No published series crosses the coffee unit break (2002) and arabica and canephora start in
-- 2012: coffee_in_husk only before the break, coffee_processed only from it, and the raw
-- "coffee_total" never appears in the serving layer. Growth decomposition pairs must sit on
-- one side of the break at both ends (start and end windows of 3 years).
{% set break_year = var('coffee_unit_break_year') %}

with series_years as (
    select 'serve_municipality_production' as model, series, year
    from {{ ref('serve_municipality_production') }}
    union all
    select 'serve_territory_production', series, year from {{ ref('serve_territory_production') }}
    union all
    select 'serve_concentration', series, year from {{ ref('serve_concentration') }}
    union all
    select 'serve_coffee_mg_biennial', series, year from {{ ref('serve_coffee_mg_biennial') }}
    union all
    select 'serve_validation_sidra', series, year from {{ ref('serve_validation_sidra') }}
    union all
    select 'serve_climate_territory_year', crop, harvest_year
    from {{ ref('serve_climate_territory_year') }}
    union all
    select 'serve_growth_decomposition (start)', series, start_anchor - 1
    from {{ ref('serve_growth_decomposition') }}
    union all
    select 'serve_growth_decomposition (end)', series, end_anchor + 1
    from {{ ref('serve_growth_decomposition') }}
)

select model, series, year
from series_years
where series = 'coffee_total'
    or (series = 'coffee_in_husk' and year >= {{ break_year }})
    or (series = 'coffee_processed' and year < {{ break_year }})
    or (series in ('coffee_arabica', 'coffee_canephora') and year < 2012)
