with source as (
    select * from {{ source('raw', 'ipca') }}
)

select
    {{ parse_date('data', '%d/%m/%Y') }} as reference_month,
    cast(valor as numeric) as monthly_change_pct,
    _ingested_at as ingested_at,
    _loaded_at as loaded_at
from source
