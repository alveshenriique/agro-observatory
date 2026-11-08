-- External validation: the project's sums over municipalities must reproduce the Brazil
-- aggregates IBGE publishes for the same table (SIDRA 5457, level N1), for production,
-- harvested area, planted area and yield (ratio of sums, within 1 kg/ha of rounding).
-- Runs only on the full data (the CI sample has 7 municipalities). Cells where IBGE's own
-- national total differs from the sum of its municipal rows are listed in
-- sidra_known_discrepancies. The comparison itself is serve_validation_sidra, the same model
-- that feeds the Método page of the site.
select *
from {{ ref('serve_validation_sidra') }}
where territory_level = 'country'
    and status = 'mismatch'
    and (select count(distinct municipality_id) from {{ ref('fct_crop_production') }}) >= 5000
