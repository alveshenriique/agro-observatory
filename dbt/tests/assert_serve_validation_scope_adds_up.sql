-- The scope of the IBGE validation covers the whole downloaded grid, and its "compared"
-- category is exactly the set of cells serve_validation_sidra compares.
with scope as (
    select
        sum(cells) as grid_cells,
        sum(case when category = 'compared' then cells else 0 end) as compared_cells
    from {{ ref('serve_validation_sidra_scope') }}
),

expected as (
    select
        (select count(*) from {{ ref('sidra_official_aggregates') }}) as grid_cells,
        (select count(*) from {{ ref('serve_validation_sidra') }}) as compared_cells
)

select scope.*, expected.grid_cells as expected_grid, expected.compared_cells as expected_compared
from scope
cross join expected
where scope.grid_cells <> expected.grid_cells
    or scope.compared_cells <> expected.compared_cells
