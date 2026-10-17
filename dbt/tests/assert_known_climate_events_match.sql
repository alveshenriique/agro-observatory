-- Known climate events should show a negative yield anomaly and the matching stress flag.
-- Association is not deterministic, so this test only warns. Events whose territory-year
-- has no normal or no trend yet (short series, CI sample) are skipped.
{{ config(severity='warn') }}

select
    events.crop,
    events.territory_level,
    events.territory_name,
    events.harvest_year,
    events.event_type,
    association.yield_anomaly_pct,
    association.water_balance_z,
    association.hot_days_z,
    association.frost_area_share,
    association.is_water_deficit,
    association.is_heat_stress,
    association.is_frost
from {{ ref('known_climate_events') }} as events
inner join {{ ref('agg_climate_yield_association') }} as association
    on association.crop = events.crop
    and association.territory_level = events.territory_level
    and association.territory_name = events.territory_name
    and association.harvest_year = events.harvest_year
where association.is_normal_available
    and association.is_trend_available
    and (
        association.yield_anomaly_pct >= 0
        or case events.event_type
            when 'water_deficit' then not association.is_water_deficit
            when 'heat' then not association.is_heat_stress
            when 'frost' then not association.is_frost
        end
    )
