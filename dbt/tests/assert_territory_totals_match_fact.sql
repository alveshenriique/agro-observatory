-- National production in the territory shares must match the production fact.
with fact as (
    select fct.crop, fct.year, sum(fct.production_t) as production_t
    from {{ ref('fct_crop_production') }} as fct
    inner join {{ ref('dim_crop') }} as crop on fct.crop = crop.crop
    where not crop.is_coffee_breakdown
    group by fct.crop, fct.year
),

shares as (
    select crop, year, territory_level, max(national_production_t) as production_t
    from {{ ref('agg_production_share_by_territory') }}
    group by crop, year, territory_level
)

select shares.*, fact.production_t as fact_production_t
from shares
left join fact on fact.crop = shares.crop and fact.year = shares.year
where coalesce(shares.production_t, 0) <> coalesce(fact.production_t, 0)
