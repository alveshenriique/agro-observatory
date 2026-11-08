-- Rankings of the serving layer: a rank exists exactly for producers (production > 0), rank 1
-- holds the largest production of its partition, and no rank exceeds the number of producers.
with ranked as (
    select
        series,
        year,
        state_id,
        immediate_region_id,
        production_t,
        rank_country,
        rank_state,
        rank_immediate_region,
        max(production_t) over (partition by series, year) as max_country,
        max(production_t) over (partition by series, year, state_id) as max_state,
        sum(case when production_t > 0 then 1 else 0 end) over (partition by series, year)
            as producers_country
    from {{ ref('serve_municipality_production') }}
)

select *
from ranked
where (production_t > 0) <> (rank_country is not null)
    or (production_t > 0) <> (rank_state is not null)
    or (production_t > 0) <> (rank_immediate_region is not null)
    or (rank_country = 1 and production_t <> max_country)
    or (rank_state = 1 and production_t <> max_state)
    or rank_country > producers_country
