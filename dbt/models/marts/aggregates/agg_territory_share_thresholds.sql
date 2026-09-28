-- Year in which each territory first reached a share of national production, per crop.
-- `first_year_reached`: first year at or above the threshold (may be a one-off spike).
-- `first_year_sustained`: first year from which the share never fell below it again.
-- Grain: crop × territory level × territory × threshold. Territories that never reached a
-- threshold (or are below it in the last year) have null years.

{% set thresholds = [0.01, 0.05] %}

with shares as (
    select * from {{ ref('agg_production_share_by_territory') }}
),

thresholds as (
    select threshold
    from unnest(array{{ thresholds }}::numeric[]) as threshold
),

flagged as (
    select
        shares.*,
        thresholds.threshold,
        coalesce(shares.share_of_national_production >= thresholds.threshold, false) as is_above
    from shares
    cross join thresholds
),

summary as (
    select
        crop,
        territory_level,
        territory_id,
        territory_name,
        threshold,
        min(year) filter (where is_above) as first_year_reached,
        max(year) filter (where not is_above) as last_year_below,
        min(year) as first_series_year,
        max(year) as last_series_year,
        max(share_of_national_production) as max_share
    from flagged
    group by crop, territory_level, territory_id, territory_name, threshold
)

select
    crop,
    territory_level,
    territory_id,
    territory_name,
    threshold,
    first_year_reached,
    case
        when last_year_below is null then first_series_year
        when last_year_below < last_series_year then last_year_below + 1
    end as first_year_sustained,
    max_share
from summary
