-- Sanity check of the source: the July 2021 frost should be visible in the previous-winter
-- window of the 2022 arabica harvest in MG (at least 15% of municipalities with a frost day).
-- Skipped when fewer than 100 municipality-years are available (CI sample).
{{ config(severity='warn') }}

with harvest_2022 as (
    select
        count(*) as municipalities,
        count(*) filter (where frost_days >= 1) as with_frost
    from {{ ref('fct_crop_climate') }}
    where crop = 'coffee_arabica' and harvest_year = 2022 and frost_coverage >= 0.9
)

select *
from harvest_2022
where municipalities >= 100 and with_frost::numeric / municipalities < 0.15
