-- Explicit check of the turn of the year: for Sorriso-MT (soybean, critical window
-- Nov-Dec of the previous year + Jan-Feb of the harvest year), the window indicators must
-- equal what is computed directly from the daily data over exactly those dates. Also checks
-- the arabica frost window (Patrocínio-MG, Jun-Aug of the previous year). Rows appear only
-- when the harvest year is in the data (both municipalities are in the CI sample).
with cases as (
    select 5107925 as municipality_id, 'soybean' as crop, 'critical' as window_name,
        harvest_year,
        {{ date_from_parts('harvest_year - 1', 11, 1) }} as window_start,
        {{ dbt.last_day(date_from_parts('harvest_year', 2, 1), 'month') }} as window_end
    from (select distinct harvest_year from {{ ref('int_climate__window_indicators') }} where municipality_id = 5107925) as years
    union all
    select 3148103, 'coffee_arabica', 'frost',
        harvest_year,
        {{ date_from_parts('harvest_year - 1', 6, 1) }},
        {{ date_from_parts('harvest_year - 1', 8, 31) }}
    from (select distinct harvest_year from {{ ref('int_climate__window_indicators') }} where municipality_id = 3148103) as years
),

direct as (
    select
        cases.municipality_id,
        cases.crop,
        cases.window_name,
        cases.harvest_year,
        min(daily.date) as first_day,
        max(daily.date) as last_day,
        count(*) as days,
        sum(daily.precipitation_mm) as precipitation_mm,
        min(daily.tmin_c) as tmin_min_c
    from cases
    inner join {{ ref('stg_brdwgd__municipality_daily') }} as daily
        on daily.municipality_id = cases.municipality_id
        and daily.date between cases.window_start and cases.window_end
    group by 1, 2, 3, 4
)

select
    direct.*,
    ind.days_in_window,
    ind.days_with_data,
    ind.precipitation_mm as model_precipitation_mm,
    ind.tmin_min_c as model_tmin_min_c
from direct
inner join {{ ref('int_climate__window_indicators') }} as ind
    on ind.municipality_id = direct.municipality_id
    and ind.crop = direct.crop
    and ind.window_name = direct.window_name
    and ind.harvest_year = direct.harvest_year
where ind.coverage >= 0.9
    and (
        direct.days <> ind.days_in_window
        or direct.days <> ind.days_with_data
        or abs(direct.precipitation_mm - ind.precipitation_mm) > 0.01
        or abs(direct.tmin_min_c - ind.tmin_min_c) > 0.01
        or extract(month from direct.first_day) <> case direct.window_name when 'critical' then 11 else 6 end
        or extract(year from direct.first_day) <> direct.harvest_year - 1
    )
