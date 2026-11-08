-- Soybean frontier: each state's and macro-region's share of the national production by year
-- (complete grid: zero where a territory produced nothing).
with states as (
    select
        shares.territory_id as state_id,
        shares.year,
        shares.production_t,
        shares.share_of_national_production
    from {{ ref('agg_production_share_by_territory') }} as shares
    where shares.crop = 'soybean' and shares.territory_level = 'state'
),

state_names as (
    select distinct state_id, state_name, region_id, region_name
    from {{ ref('dim_municipality') }}
),

territories as (
    select
        'state' as territory_level,
        states.state_id as territory_id,
        state_names.state_name as territory_name,
        states.year,
        states.production_t,
        states.share_of_national_production
    from states
    inner join state_names on state_names.state_id = states.state_id
    union all
    select
        'macro_region',
        state_names.region_id,
        state_names.region_name,
        states.year,
        sum(states.production_t),
        sum(states.share_of_national_production)
    from states
    inner join state_names on state_names.state_id = states.state_id
    group by state_names.region_id, state_names.region_name, states.year
)

select
    territory_level,
    territory_id,
    territory_name,
    year,
    {{ round_to_int('production_t') }} as production_t,
    {{ round_to('share_of_national_production', 4) }} as share_of_national_production
from territories
