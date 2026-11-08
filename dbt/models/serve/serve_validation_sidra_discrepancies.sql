-- The cells of the external validation that are not an exact match, for the Método page: the
-- documented differences of the source itself (and any mismatch, which fails the build on the
-- full data). Values rounded for display.
select
    territory_level,
    territory_id,
    territory_name,
    series,
    year,
    variable,
    {{ round_to('official_value', 0) }} as official_value,
    {{ round_to('our_value', 0) }} as our_value,
    {{ round_to('difference', 0) }} as difference,
    {{ round_to('difference / nullif(' ~ as_float('official_value') ~ ', 0)', 4) }} as relative_difference,
    status,
    reason
from {{ ref('serve_validation_sidra') }}
where status <> 'match'
