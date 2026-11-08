-- Soybean frontier: the first year each state reached (and sustained) 1% and 5% of the
-- national production.
select
    shares.territory_id,
    names.state_name as territory_name,
    {{ round_to('shares.threshold', 2) }} as threshold,
    shares.first_year_reached,
    shares.first_year_sustained,
    {{ round_to('shares.max_share', 4) }} as max_share
from {{ ref('agg_territory_share_thresholds') }} as shares
inner join (
    select distinct state_id, state_name from {{ ref('dim_municipality') }}
) as names on names.state_id = shares.territory_id
where shares.crop = 'soybean' and shares.territory_level = 'state'
