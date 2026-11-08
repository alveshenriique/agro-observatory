-- Every territorial aggregate of the serving layer is the sum of the published municipal
-- rows of that territory (quantities exactly; integers on both sides), with the right counts.
with municipalities as (
    select
        production.*,
        dim.region_id
    from {{ ref('serve_municipality_production') }} as production
    inner join {{ ref('serve_municipalities') }} as dim
        on dim.municipality_id = production.municipality_id
),

expected as (
    {% for level, column in [('country', '1'), ('macro_region', 'region_id'), ('state', 'state_id'), ('immediate_region', 'immediate_region_id')] %}
    select
        '{{ level }}' as territory_level,
        {{ column }} as territory_id,
        series,
        year,
        sum(production_t) as production_t,
        sum(harvested_area_ha) as harvested_area_ha,
        sum(planted_or_bearing_area_ha) as planted_or_bearing_area_ha,
        count(*) as municipalities_with_data,
        sum(case when production_t > 0 then 1 else 0 end) as producing_municipalities
    from municipalities
    group by {% if column != '1' %}{{ column }}, {% endif %}series, year
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
)

select expected.*, territory.territory_id as published_territory_id
from expected
full outer join {{ ref('serve_territory_production') }} as territory
    on territory.territory_level = expected.territory_level
    and territory.territory_id = expected.territory_id
    and territory.series = expected.series
    and territory.year = expected.year
where territory.territory_id is null
    or expected.territory_id is null
    or territory.production_t <> expected.production_t
    or territory.harvested_area_ha <> expected.harvested_area_ha
    or territory.planted_or_bearing_area_ha <> expected.planted_or_bearing_area_ha
    or territory.municipalities_with_data <> expected.municipalities_with_data
    or territory.producing_municipalities <> expected.producing_municipalities
