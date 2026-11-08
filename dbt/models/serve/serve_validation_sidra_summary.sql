-- Counts of the external validation against IBGE's aggregates, by level, variable and status
-- (see serve_validation_sidra).
select
    territory_level,
    variable,
    status,
    count(*) as cells,
    min(year) as first_year,
    max(year) as last_year
from {{ ref('serve_validation_sidra') }}
group by territory_level, variable, status
