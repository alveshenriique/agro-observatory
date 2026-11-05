-- Conformed year dimension, shared by the production fact and (phase 8) the climate fact.
-- The year spine is built from a number series (dbt_utils) clipped to the PAM's first and
-- last years, so it does not depend on every year having data.

with bounds as (
    select min(year) as first_year, max(year) as last_year
    from {{ ref('int_pam__crop_year') }}
),

numbers as (
    {{ dbt_utils.generate_series(200) }}
),

years as (
    select cast(bounds.first_year + numbers.generated_number - 1 as {{ dbt.type_int() }}) as year
    from bounds
    cross join numbers
    where bounds.first_year + numbers.generated_number - 1 <= bounds.last_year
)

select
    years.year,
    cast(div(years.year, 10) * 10 as {{ dbt.type_int() }}) as decade,
    cast(div(years.year, 10) * 10 as {{ dbt.type_string() }}) || 's' as decade_label,
    coalesce(
        years.year >= {{ var('real_value_first_year') }} and ipca.is_complete_year,
        false
    ) as is_real_value_available,
    -- Unit in which the PAM measures coffee production (table 5457, note 4): beans still in
    -- the husk until 2001, processed beans from 2002. Coffee series must not cross this.
    case
        when years.year >= {{ var('coffee_unit_break_year') }} then 'coffee_processed'
        else 'coffee_in_husk'
    end as coffee_production_unit,
    years.year >= {{ var('coffee_unit_break_year') }} as is_coffee_processed_unit
from years
left join {{ ref('int_bcb__ipca_annual') }} as ipca
    on years.year = ipca.year
