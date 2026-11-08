-- External validation against a different source: CONAB's soybean estimates by state (crop
-- survey) versus the project's PAM sums (municipal census). The methodologies differ, so
-- this only warns when planted area or production differ by more than 10% in a state with
-- at least 100,000 ha, from harvest year 2010 on. Runs only on the full data. The comparison
-- itself is serve_validation_conab, the same model that feeds the Método page of the site.
{{ config(severity='warn') }}

select *
from {{ ref('serve_validation_conab') }}
where is_beyond_tolerance
    and (select count(distinct municipality_id) from {{ ref('fct_crop_production') }}) >= 5000
