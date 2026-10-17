-- Climatological normal (mean and standard deviation) of each window indicator per
-- municipality × crop × window, over the harvest years of the reference period
-- (`climate_normal_start_year`-`climate_normal_end_year`, the WMO 1991-2020 normal).
-- Only complete windows count; the normal is available with at least
-- `climate_normal_min_years` of them.
{{ config(materialized='table') }}

{% set indicators = [
    'precipitation_mm', 'eto_mm', 'water_balance_mm', 'tmax_mean_c', 'tmin_mean_c',
    'tmin_min_c', 'hot_days', 'severe_hot_days', 'dry_days', 'longest_dry_spell_days',
    'frost_days', 'severe_frost_days',
] %}

select
    municipality_id,
    crop,
    window_name,
    count(*) as n_years,
    count(*) >= {{ var('climate_normal_min_years') }} as is_normal_available,
    {% for indicator in indicators %}
    avg({{ indicator }}) as {{ indicator }}_mean,
    stddev_samp({{ indicator }}) as {{ indicator }}_sd{{ "," if not loop.last }}
    {% endfor %}
from {{ ref('int_climate__window_indicators') }}
where harvest_year between {{ var('climate_normal_start_year') }} and {{ var('climate_normal_end_year') }}
    and precipitation_mm is not null  -- complete windows only (nulled below the coverage floor)
group by municipality_id, crop, window_name
