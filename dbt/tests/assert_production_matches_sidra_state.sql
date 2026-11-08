-- External validation at the state level (SIDRA 5457, level N3): the project's sums over
-- municipalities must reproduce the state aggregates IBGE publishes. Runs only on the full
-- data (the CI sample has 7 municipalities).
--
-- IBGE publishes the historical state series with the territory of each year: before the
-- splits, "Mato Grosso" includes today's Mato Grosso do Sul (until 1978) and "Goiás"
-- includes Tocantins (until 1988). The project uses the current mesh, so those years are
-- compared on the merged territories. Cells where IBGE's own state total differs from the
-- sum of its municipal rows (1974 RJ, 1998, 2002, 2010-2011) are listed in
-- sidra_known_discrepancies. The comparison itself is serve_validation_sidra, the same model
-- that feeds the Método page of the site.
select *
from {{ ref('serve_validation_sidra') }}
where territory_level = 'state'
    and status = 'mismatch'
    and (select count(distinct municipality_id) from {{ ref('fct_crop_production') }}) >= 5000
