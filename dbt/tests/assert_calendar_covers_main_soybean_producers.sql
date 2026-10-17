-- Every state with at least 0.5% of the national soybean production in the last five years
-- must have a soybean calendar. (Arabica coffee is scoped to MG by decision, so it is not
-- checked here.)
with recent as (
    select max(year) as last_year
    from {{ ref('fct_crop_production') }}
    where crop = 'soybean'
),

share_by_state as (
    select
        dim.state_abbreviation,
        sum(fct.production_t) / sum(sum(fct.production_t)) over () as share
    from {{ ref('fct_crop_production') }} as fct
    inner join {{ ref('dim_municipality') }} as dim
        on dim.municipality_id = fct.municipality_id
    cross join recent
    where fct.crop = 'soybean' and fct.year > recent.last_year - 5
    group by dim.state_abbreviation
),

covered as (
    select distinct state_abbreviation
    from {{ ref('crop_calendar_windows') }}
    where crop = 'soybean'
)

select share_by_state.*
from share_by_state
left join covered on covered.state_abbreviation = share_by_state.state_abbreviation
where share_by_state.share >= 0.005 and covered.state_abbreviation is null
