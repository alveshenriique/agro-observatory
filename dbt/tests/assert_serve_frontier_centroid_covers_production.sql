-- The soybean centroid uses every producing municipality: its production equals the national
-- soybean production of the year (no producer is missing a representative point).
select centroid.year, centroid.production_t, country.production_t as national_production_t
from {{ ref('serve_soybean_frontier_centroid') }} as centroid
inner join {{ ref('serve_territory_production') }} as country
    on country.territory_level = 'country'
    and country.series = 'soybean'
    and country.year = centroid.year
where centroid.production_t <> country.production_t
