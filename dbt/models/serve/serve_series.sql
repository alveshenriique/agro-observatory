-- The published series. Each crop is one series, except coffee total, which is split at the
-- unit break of the PAM (coffee "em coco" until 2001, "beneficiado" from 2002): the two halves
-- are separate series and nothing in the serving layer crosses the break.
with labels as (
    select 'soybean' as series, 'soybean' as crop, 1 as sort_order,
        'Soja' as series_name_pt, 't' as production_unit_pt,
        'área plantada' as area_name_pt, 'soybean' as climate_crop
    union all
    select 'corn', 'corn', 2, 'Milho', 't', 'área plantada', null
    union all
    select 'coffee_in_husk', 'coffee_total', 3, 'Café, em coco (até 2001)',
        't de café em coco', 'área em produção', null
    union all
    select 'coffee_processed', 'coffee_total', 4, 'Café, beneficiado (desde 2002)',
        't de café beneficiado', 'área em produção', null
    union all
    select 'coffee_arabica', 'coffee_arabica', 5, 'Café arábica',
        't de café beneficiado', 'área em produção', 'coffee_arabica'
    union all
    select 'coffee_canephora', 'coffee_canephora', 6, 'Café canéfora (conilon e robusta)',
        't de café beneficiado', 'área em produção', null
),

years as (
    select
        {{ serve_series('crop', 'year') }} as series,
        min(year) as first_year,
        max(year) as last_year
    from {{ ref('fct_crop_production') }}
    group by 1
)

select
    labels.series,
    labels.crop,
    labels.sort_order,
    labels.series_name_pt,
    labels.production_unit_pt,
    labels.area_name_pt,
    years.first_year,
    years.last_year,
    -- Real (deflated) values exist only from the Plano Real on.
    greatest(years.first_year, {{ var('real_value_first_year') }}) as real_value_first_year,
    labels.climate_crop
from labels
inner join years on years.series = labels.series
