-- The deflation base year must have all 12 months of IPCA.
-- A one-row subquery as FROM: BigQuery does not accept WHERE without FROM (Postgres does).
select base_year
from (select {{ var('deflation_base_year') }} as base_year) as base
where not exists (
    select 1
    from {{ ref('int_bcb__ipca_annual') }}
    where year = {{ var('deflation_base_year') }} and is_complete_year
)
