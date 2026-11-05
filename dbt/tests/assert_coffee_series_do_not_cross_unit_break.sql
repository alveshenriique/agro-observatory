-- Crops with a unit break in the source (dim_crop.series_break_year; coffee: in husk until
-- 2001, processed from 2002) must never be summed or compared across the break by the marts
-- that look at more than one year. Checks the growth decomposition (no period window
-- touches both units, no pair compares the two) and the MG biennial series (each series on
-- one side of the break, so no ratio or change crosses it). Within-year marts (shares,
-- concentration) are unit-free and not checked.
with breaks as (
    select crop, series_break_year
    from {{ ref('dim_crop') }}
    where series_break_year is not null
),

decomposition as (
    select
        'agg_production_growth_decomposition' as mart,
        decomposition.crop,
        cast(decomposition.start_anchor as {{ dbt.type_string() }}) || '-'
            || cast(decomposition.end_anchor as {{ dbt.type_string() }}) as detail
    from {{ ref('agg_production_growth_decomposition') }} as decomposition
    inner join breaks on breaks.crop = decomposition.crop
    where decomposition.start_anchor - 1 < breaks.series_break_year
        or decomposition.end_anchor - 1 < breaks.series_break_year
),

biennial as (
    select
        'agg_coffee_mg_biennial' as mart,
        biennial.crop,
        biennial.series as detail
    from {{ ref('agg_coffee_mg_biennial') }} as biennial
    inner join breaks on breaks.crop = biennial.crop
    group by biennial.crop, biennial.series, breaks.series_break_year
    having min(biennial.year) < breaks.series_break_year
        and max(biennial.year) >= breaks.series_break_year
)

select * from decomposition
union all
select * from biennial
