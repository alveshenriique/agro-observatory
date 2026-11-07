-- Reads the daily climate, which only the local Postgres has (macro use_derived_climate_source).
{{ config(enabled=not use_derived_climate_source()) }}

-- Daily climate by municipality (BR-DWGD aggregated by the ingestion). Already typed in raw;
-- nothing to convert. Kept as a view so partition pruning by date still applies downstream.
with source as (
    select * from {{ source('raw', 'brdwgd_municipality_daily') }}
)

select
    municipality_id,
    date,
    precipitation_mm,
    eto_mm,
    tmax_c,
    tmin_c
from source
