with source as (
    select * from {{ source('raw', 'ipca') }}
)

select
    to_date(data, 'DD/MM/YYYY') as reference_month,
    valor::numeric as monthly_change_pct,
    _ingested_at as ingested_at,
    _loaded_at as loaded_at
from source
