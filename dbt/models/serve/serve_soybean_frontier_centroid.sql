-- Soybean frontier: production-weighted centroid of the producing municipalities by year,
-- from the representative point of each municipality (always inside its polygon). The mean of
-- latitudes and longitudes is a planar approximation, adequate to draw the path of the
-- frontier over the decades.
select
    fct.year,
    {{ round_to(as_float('sum(fct.production_t * dim.representative_lat)') ~ ' / ' ~ as_float('sum(fct.production_t)'), 4) }}
        as centroid_lat,
    {{ round_to(as_float('sum(fct.production_t * dim.representative_lon)') ~ ' / ' ~ as_float('sum(fct.production_t)'), 4) }}
        as centroid_lon,
    {{ round_to_int('sum(fct.production_t)') }} as production_t,
    count(*) as producing_municipalities
from {{ ref('fct_crop_production') }} as fct
inner join {{ ref('dim_municipality') }} as dim
    on dim.municipality_id = fct.municipality_id
where fct.crop = 'soybean'
    and fct.production_t > 0
    and dim.representative_lat is not null
group by fct.year
