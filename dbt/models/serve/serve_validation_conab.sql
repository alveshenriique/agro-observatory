-- External validation against a source with a different method: CONAB's soybean estimates by
-- state (crop survey) versus the PAM sums (municipal census), from harvest year 2010. A
-- state-year is compared when CONAB reports at least 100,000 ha planted, and flagged when
-- planted area or production differ by more than 10% (the test assert_soybean_matches_conab
-- warns on those). Flags are computed on the exact values; relative differences are rounded
-- for display.
with ours as (
    select
        dim.state_abbreviation,
        fct.year as harvest_year,
        sum(fct.planted_or_bearing_area_ha) as planted_area_ha,
        sum(fct.production_t) as production_t
    from {{ ref('fct_crop_production') }} as fct
    inner join {{ ref('dim_municipality') }} as dim on dim.municipality_id = fct.municipality_id
    where fct.crop = 'soybean' and fct.year >= 2010
    group by dim.state_abbreviation, fct.year
),

compared as (
    select
        conab.state_abbreviation,
        conab.harvest_year,
        conab.planted_area_ha as conab_planted_area_ha,
        ours.planted_area_ha as pam_planted_area_ha,
        {{ as_float('ours.planted_area_ha') }} / nullif({{ as_float('conab.planted_area_ha') }}, 0) - 1
            as planted_area_relative_difference,
        conab.production_t as conab_production_t,
        ours.production_t as pam_production_t,
        {{ as_float('ours.production_t') }} / nullif({{ as_float('conab.production_t') }}, 0) - 1
            as production_relative_difference,
        conab.planted_area_ha >= 100000 as is_compared
    from {{ ref('conab_soybean_series') }} as conab
    inner join ours
        on ours.state_abbreviation = conab.state_abbreviation
        and ours.harvest_year = conab.harvest_year
)

select
    state_abbreviation,
    harvest_year,
    {{ round_to_int('conab_planted_area_ha') }} as conab_planted_area_ha,
    {{ round_to_int('pam_planted_area_ha') }} as pam_planted_area_ha,
    {{ round_to('planted_area_relative_difference', 4) }} as planted_area_relative_difference,
    {{ round_to_int('conab_production_t') }} as conab_production_t,
    {{ round_to_int('pam_production_t') }} as pam_production_t,
    {{ round_to('production_relative_difference', 4) }} as production_relative_difference,
    is_compared,
    is_compared and (
        abs(planted_area_relative_difference) > 0.10
        or abs(production_relative_difference) > 0.10
    ) as is_beyond_tolerance
from compared
