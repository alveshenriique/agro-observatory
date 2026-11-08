-- Production concentration (municipalities for 50% and 80% of the national production, HHI)
-- by published series and year. Coffee total is split at 2002 even though these measures have
-- no unit: the husk-to-processed ratio varies between regions, so shares could move
-- artificially at the break.
select
    {{ serve_series('crop', 'year') }} as series,
    year,
    producing_municipalities,
    {{ round_to_int('national_production_t') }} as national_production_t,
    municipalities_for_50pct,
    municipalities_for_80pct,
    {{ round_to('share_of_producers_for_50pct', 4) }} as share_of_producers_for_50pct,
    {{ round_to('hhi', 1) }} as hhi
from {{ ref('agg_production_concentration') }}
