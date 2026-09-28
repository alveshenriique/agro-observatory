-- Production concentration across municipalities, per crop and year: how many municipalities
-- account for 50% and 80% of national production, and the Herfindahl-Hirschman index (HHI).
-- Municipality counts are affected by municipality splits; the HHI is more robust to them.
-- Coffee breakdown crops are kept: concentration is computed within each crop, never summed
-- across crops. Grain: crop × year.

with production as (
    select crop, year, municipality_id, production_t
    from {{ ref('fct_crop_production') }}
    where production_t > 0
),

ranked as (
    select
        *,
        production_t / sum(production_t) over (partition by crop, year) as share,
        row_number() over (
            partition by crop, year order by production_t desc, municipality_id
        ) as rank
    from production
),

cumulative as (
    select
        *,
        sum(share) over (partition by crop, year order by rank) as cumulative_share
    from ranked
)

select
    crop,
    year,
    count(*) as producing_municipalities,
    sum(production_t) as national_production_t,
    min(rank) filter (where cumulative_share >= 0.5) as municipalities_for_50pct,
    min(rank) filter (where cumulative_share >= 0.8) as municipalities_for_80pct,
    min(rank) filter (where cumulative_share >= 0.5)::numeric / count(*)
        as share_of_producers_for_50pct,
    -- HHI on the 0-10,000 scale (sum of squared percentage shares).
    sum(power(share * 100, 2)) as hhi
from cumulative
group by crop, year
