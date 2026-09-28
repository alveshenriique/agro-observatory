-- The deflation base year must have all 12 months of IPCA.
select {{ var('deflation_base_year') }} as base_year
where not exists (
    select 1
    from {{ ref('int_bcb__ipca_annual') }}
    where year = {{ var('deflation_base_year') }} and is_complete_year
)
