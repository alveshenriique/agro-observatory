-- Index of all municipalities of the current mesh, in the canonical order of the published
-- files (ascending IBGE code), including the 7 without PAM data.
select
    municipality_id,
    municipality_name,
    state_id,
    state_abbreviation,
    state_name,
    region_id,
    region_name,
    intermediate_region_id,
    intermediate_region_name,
    immediate_region_id,
    immediate_region_name,
    first_pam_year,
    {{ round_to('representative_lat', 4) }} as representative_lat,
    {{ round_to('representative_lon', 4) }} as representative_lon
from {{ ref('dim_municipality') }}
