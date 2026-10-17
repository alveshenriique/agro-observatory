-- Municipality × crop pairs with any production, restricted to the crops and states that have
-- a crop calendar (soybean in the states covered by CONAB; arabica coffee in MG). Climate is
-- only aggregated for these pairs.
with calendar_scope as (
    select distinct crop, state_abbreviation
    from {{ ref('crop_calendar_windows') }}
)

select distinct
    fct.municipality_id,
    fct.crop,
    dim.state_abbreviation
from {{ ref('fct_crop_production') }} as fct
inner join {{ ref('dim_municipality') }} as dim
    on fct.municipality_id = dim.municipality_id
inner join calendar_scope
    on calendar_scope.crop = fct.crop
    and calendar_scope.state_abbreviation = dim.state_abbreviation
where fct.production_t > 0
