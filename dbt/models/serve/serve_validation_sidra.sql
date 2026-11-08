-- External validation against IBGE's own aggregates (SIDRA 5457, levels N1 and N3): every
-- published Brazil and state value compared with the project's sums over municipalities, cell
-- by cell (territory x crop x year x variable). Status: `match` (within rounding: 0.5 for
-- quantities, 1 kg/ha for yield, a ratio of sums), `documented` (IBGE's own total differs
-- from the sum of its municipal rows; listed with the reason in sidra_known_discrepancies) or
-- `mismatch`. The tests assert_production_matches_sidra_country and _state fail on any
-- mismatch with the full data; the Método page shows the counts.
--
-- State series: IBGE publishes them with the territory of each year, so before the splits
-- "Mato Grosso" includes today's Mato Grosso do Sul (until 1978) and "Goiás" includes
-- Tocantins (until 1988); those years are compared on the merged territories.
with municipal as (
    select
        fct.crop,
        fct.year,
        case
            when fct.year <= 1978 and dim.state_id in (50, 51) then 51  -- MT + MS -> Mato Grosso
            when fct.year <= 1988 and dim.state_id in (52, 17) then 52  -- GO + TO -> Goiás
            else dim.state_id
        end as state_id,
        fct.production_t,
        fct.harvested_area_ha,
        fct.planted_or_bearing_area_ha as planted_area_ha
    from {{ ref('fct_crop_production') }} as fct
    inner join {{ ref('dim_municipality') }} as dim on dim.municipality_id = fct.municipality_id
),

ours as (
    select
        'country' as territory_level,
        1 as territory_id,
        crop,
        year,
        sum(production_t) as production_t,
        sum(harvested_area_ha) as harvested_area_ha,
        sum(planted_area_ha) as planted_area_ha,
        {{ as_float('sum(production_t)') }} / nullif({{ as_float('sum(harvested_area_ha)') }}, 0) * 1000
            as yield_kg_ha
    from municipal
    group by crop, year
    union all
    select
        'state',
        state_id,
        crop,
        year,
        sum(production_t),
        sum(harvested_area_ha),
        sum(planted_area_ha),
        {{ as_float('sum(production_t)') }} / nullif({{ as_float('sum(harvested_area_ha)') }}, 0) * 1000
    from municipal
    group by state_id, crop, year
),

official as (
    select territory_level, territory_id, territory_name, crop, year, variable, official_value
    from {{ ref('sidra_official_aggregates') }}
    where official_value is not null
),

known as (
    select territory_level, territory_id, crop, year, variable, reason
    from {{ ref('sidra_known_discrepancies') }}
),

compared as (
    select
        official.territory_level,
        official.territory_id,
        official.territory_name,
        official.crop,
        official.year,
        official.variable,
        official.official_value,
        case official.variable
            when 'production_t' then {{ as_float('ours.production_t') }}
            when 'harvested_area_ha' then {{ as_float('ours.harvested_area_ha') }}
            when 'planted_area_ha' then {{ as_float('ours.planted_area_ha') }}
            when 'yield_kg_ha' then ours.yield_kg_ha
        end as our_value,
        case when official.variable = 'yield_kg_ha' then 1 else 0.5 end as tolerance,
        known.reason
    from official
    left join ours
        on ours.territory_level = official.territory_level
        and ours.territory_id = official.territory_id
        and ours.crop = official.crop
        and ours.year = official.year
    left join known
        on known.territory_level = official.territory_level
        and known.territory_id = official.territory_id
        and known.crop = official.crop
        and known.year = official.year
        and known.variable = official.variable
)

select
    territory_level,
    territory_id,
    territory_name,
    crop,
    {{ serve_series('crop', 'year') }} as series,
    year,
    variable,
    official_value,
    our_value,
    our_value - {{ as_float('official_value') }} as difference,
    tolerance,
    case
        when reason is not null then 'documented'
        when abs(coalesce(our_value, 0) - {{ as_float('official_value') }}) <= tolerance then 'match'
        else 'mismatch'
    end as status,
    reason
from compared
