-- From 2012 on, arabica + canephora must add up to coffee_total for each municipality and year.
with coffee as (
    select
        municipality_id,
        year,
        sum(production_t) filter (where crop = 'coffee_total') as total_t,
        sum(production_t) filter (where crop in ('coffee_arabica', 'coffee_canephora')) as breakdown_t
    from {{ ref('fct_crop_production') }}
    where crop like 'coffee%' and year >= 2012
    group by municipality_id, year
)

select *
from coffee
where coalesce(total_t, 0) <> coalesce(breakdown_t, 0)
