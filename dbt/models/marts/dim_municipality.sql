with localities as (
    select * from {{ ref('stg_ibge__localities') }}
),

first_pam_year as (
    select municipality_id, min(year) as first_pam_year
    from {{ ref('int_pam__crop_year') }}
    where has_data
    group by municipality_id
)

select
    localities.municipality_id,
    localities.municipality_name,
    localities.state_id,
    localities.state_abbreviation,
    localities.state_name,
    localities.region_id,
    localities.region_abbreviation,
    localities.region_name,
    localities.intermediate_region_id,
    localities.intermediate_region_name,
    localities.immediate_region_id,
    localities.immediate_region_name,
    localities.mesoregion_id,
    localities.mesoregion_name,
    localities.microregion_id,
    localities.microregion_name,
    -- First year with any data for the tracked crops. A proxy for when municipalities
    -- created by splitting appear in the series; null when the PAM has no data at all.
    first_pam_year.first_pam_year
from localities
left join first_pam_year
    on localities.municipality_id = first_pam_year.municipality_id
