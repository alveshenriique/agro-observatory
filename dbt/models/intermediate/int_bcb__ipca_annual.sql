-- Annual IPCA price level and deflator to the base year (var `deflation_base_year`).
-- The monthly changes are chained into an index; the annual level is the mean of the 12
-- monthly index values, matching an annual flow such as the production value.

with monthly as (
    select
        reference_month,
        -- Cumulative product of (1 + change), computed as exp(sum(ln(...))).
        exp(sum(ln(1 + monthly_change_pct / 100)) over (order by reference_month)) as price_index
    from {{ ref('stg_bcb__ipca') }}
),

annual as (
    select
        extract(year from reference_month)::integer as year,
        avg(price_index) as avg_price_index,
        count(*) as months
    from monthly
    group by 1
),

base as (
    select avg_price_index as base_price_index
    from annual
    where year = {{ var('deflation_base_year') }}
)

select
    annual.year,
    annual.avg_price_index,
    annual.months,
    annual.months = 12 as is_complete_year,
    base.base_price_index / annual.avg_price_index as deflator_to_base_year
from annual
cross join base
