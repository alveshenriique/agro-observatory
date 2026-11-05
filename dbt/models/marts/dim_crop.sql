select
    crop,
    product_id,
    crop_name_pt,
    -- Arabica and canephora detail coffee_total: exclude them when summing across crops.
    is_coffee_breakdown,
    -- First year of a new measurement unit in the source (coffee: in husk until 2001,
    -- processed from 2002). Production and yield must not be compared across it.
    series_break_year,
    series_break_note
from {{ ref('crops') }}
