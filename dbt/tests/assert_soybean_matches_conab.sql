-- External validation against a different source: CONAB's soybean estimates by state (crop
-- survey) versus the project's PAM sums (municipal census). The methodologies differ, so
-- this only warns when planted area or production differ by more than 10% in a state with
-- at least 100,000 ha, from harvest year 2010 on. Runs only on the full data.
{{ config(severity='warn') }}

with ours as (
    select
        dim.state_abbreviation,
        fct.year as harvest_year,
        sum(fct.planted_area_ha) as planted_area_ha,
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
        ours.planted_area_ha / nullif(conab.planted_area_ha, 0) - 1 as planted_area_diff_pct,
        conab.production_t as conab_production_t,
        ours.production_t as pam_production_t,
        ours.production_t / nullif(conab.production_t, 0) - 1 as production_diff_pct
    from {{ ref('conab_soybean_series') }} as conab
    inner join ours
        on ours.state_abbreviation = conab.state_abbreviation
        and ours.harvest_year = conab.harvest_year
    where conab.planted_area_ha >= 100000
)

select *
from compared
where (select count(distinct municipality_id) from {{ ref('fct_crop_production') }}) >= 5000
    and (abs(planted_area_diff_pct) > 0.10 or abs(production_diff_pct) > 0.10)
