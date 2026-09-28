select
    crop,
    product_id,
    crop_name_pt,
    -- Arabica and canephora detail coffee_total: exclude them when summing across crops.
    is_coffee_breakdown
from {{ ref('crops') }}
