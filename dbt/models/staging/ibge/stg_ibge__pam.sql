with source as (
    select * from {{ source('raw', 'pam') }}
),

renamed as (
    select
        cast({{ source_column('D1C') }} as {{ dbt.type_int() }}) as municipality_id,
        cast({{ source_column('D4C') }} as {{ dbt.type_int() }}) as product_id,
        case {{ source_column('D4C') }}
            when '40124' then 'soybean'
            when '40122' then 'corn'
            when '40139' then 'coffee_total'
            when '40140' then 'coffee_arabica'
            when '40141' then 'coffee_canephora'
        end as crop,
        cast({{ source_column('D3C') }} as {{ dbt.type_int() }}) as year,
        cast({{ source_column('D2C') }} as {{ dbt.type_int() }}) as variable_id,
        case {{ source_column('D2C') }}
            when '8331' then 'planted_area'
            when '216' then 'harvested_area'
            when '214' then 'production_quantity'
            when '112' then 'average_yield'
            when '215' then 'production_value'
        end as variable,
        nullif({{ source_column('MN') }}, '') as unit,
        {{ source_column('V') }} as raw_value,
        _ingested_at as ingested_at,
        _loaded_at as loaded_at
    from source
),

typed as (
    select
        *,
        -- IBGE special symbols: "-" absolute zero, "0" zero from rounding,
        -- "..." not available, ".." not applicable, "X" suppressed for confidentiality.
        case
            when raw_value = '-' then 'absolute_zero'
            when raw_value = '0' then 'rounded_zero'
            when raw_value = '...' then 'not_available'
            when raw_value = '..' then 'not_applicable'
            when raw_value = 'X' then 'confidential'
            when {{ regex_match('raw_value', '^[0-9]+([.][0-9]+)?$') }} then 'reported'
        end as value_status
    from renamed
)

select
    municipality_id,
    product_id,
    crop,
    year,
    variable_id,
    variable,
    unit,
    case
        when value_status in ('absolute_zero', 'rounded_zero') then 0
        when value_status = 'reported' then cast(raw_value as numeric)
    end as value,
    value_status,
    raw_value,
    ingested_at,
    loaded_at
from typed
