-- Conformed year dimension, shared by the production fact and (phase 8) the climate fact.

with bounds as (
    select min(year) as first_year, max(year) as last_year
    from {{ ref('int_pam__crop_year') }}
),

years as (
    select generate_series(first_year, last_year)::integer as year
    from bounds
)

select
    years.year,
    (years.year / 10 * 10)::integer as decade,
    (years.year / 10 * 10)::text || 's' as decade_label,
    coalesce(
        years.year >= {{ var('real_value_first_year') }} and ipca.is_complete_year,
        false
    ) as is_real_value_available
from years
left join {{ ref('int_bcb__ipca_annual') }} as ipca
    on years.year = ipca.year
