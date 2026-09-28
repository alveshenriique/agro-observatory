-- Territory shares must add up to 100% of national production in every crop, year and level
-- (whenever there is any production).
select crop, year, territory_level, sum(share_of_national_production) as total_share
from {{ ref('agg_production_share_by_territory') }}
group by crop, year, territory_level
having max(national_production_t) > 0
    and abs(sum(share_of_national_production) - 1) > 1e-9
