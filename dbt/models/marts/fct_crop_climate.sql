-- Climate per municipality × crop × harvest year, for municipality-years with production,
-- pivoted from the window indicators: soybean has `critical_*` and `season_*` columns, arabica
-- coffee has `flowering_*`, `filling_*` and `frost_*`; the others are null. `*_z` columns are
-- anomalies against the municipality's 1991-2020 normal; `*_has_normal` says whether the
-- normal exists (false in short series, such as the CI sample).
{% set full_set = [
    'days_in_window', 'coverage', 'precipitation_mm', 'eto_mm', 'water_balance_mm',
    'tmax_mean_c', 'hot_days', 'severe_hot_days', 'dry_days', 'longest_dry_spell_days',
] %}
{% set z_columns = ['water_balance_mm', 'hot_days', 'longest_dry_spell_days', 'tmin_min_c', 'frost_days'] %}
{# z-scores are dimensionless, so their names drop the unit suffix. #}
{% set z_names = {
    'water_balance_mm': 'water_balance_z', 'hot_days': 'hot_days_z',
    'longest_dry_spell_days': 'longest_dry_spell_z', 'tmin_min_c': 'tmin_min_z', 'frost_days': 'frost_days_z',
} %}
{% set water_z = ['water_balance_mm', 'hot_days', 'longest_dry_spell_days'] %}
{% set windows = [
    {'name': 'critical', 'columns': full_set, 'z': water_z, 'pct': true, 'aliases': {}},
    {'name': 'season', 'columns': ['days_in_window', 'coverage', 'precipitation_mm', 'eto_mm', 'water_balance_mm'],
     'z': ['water_balance_mm'], 'pct': true, 'aliases': {}},
    {'name': 'flowering', 'columns': full_set, 'z': water_z, 'pct': true, 'aliases': {}},
    {'name': 'filling', 'columns': full_set, 'z': water_z, 'pct': true, 'aliases': {}},
    {'name': 'frost', 'columns': ['days_in_window', 'coverage', 'tmin_mean_c', 'tmin_min_c', 'frost_days', 'severe_frost_days'],
     'z': ['tmin_min_c', 'frost_days'], 'pct': false,
     'aliases': {'frost_days': 'frost_days', 'severe_frost_days': 'frost_severe_days', 'frost_days_z': 'frost_days_z'}},
] %}

with producing_years as (
    select fct.municipality_id, fct.crop, fct.year as harvest_year
    from {{ ref('fct_crop_production') }} as fct
    inner join {{ ref('int_climate__producing_municipalities') }} as producing
        on producing.municipality_id = fct.municipality_id
        and producing.crop = fct.crop
    where fct.production_t > 0
        and fct.year >= {{ var('climate_first_harvest_year') }}
),

indicators as (
    select
        ind.*,
        normals.is_normal_available,
        {% for column in z_columns %}
        (ind.{{ column }} - normals.{{ column }}_mean) / nullif(normals.{{ column }}_sd, 0)
            as {{ z_names[column] }},
        {% endfor %}
        ind.precipitation_mm / nullif(normals.precipitation_mm_mean, 0) * 100 as precipitation_pct_of_normal
    from {{ ref('int_climate__window_indicators') }} as ind
    left join {{ ref('int_climate__window_normals') }} as normals
        on normals.municipality_id = ind.municipality_id
        and normals.crop = ind.crop
        and normals.window_name = ind.window_name
)

select
    producing_years.municipality_id,
    producing_years.crop,
    producing_years.harvest_year,
    {% for window in windows %}
    {% set w = window.name %}
    -- {{ w }} window
    {% for column in window.columns %}
    max(case when indicators.window_name = '{{ w }}' then indicators.{{ column }} end)
        as {{ window.aliases.get(column, w ~ '_' ~ column) }},
    {% endfor %}
    {% if window.pct %}
    max(case when indicators.window_name = '{{ w }}' then indicators.precipitation_pct_of_normal end)
        as {{ w }}_precipitation_pct_of_normal,
    {% endif %}
    {% for column in window.z %}
    max(case when indicators.window_name = '{{ w }}' then indicators.{{ z_names[column] }} end)
        as {{ window.aliases.get(z_names[column], w ~ '_' ~ z_names[column]) }},
    {% endfor %}
    coalesce(bool_or(case when indicators.window_name = '{{ w }}' then indicators.is_normal_available end), false)
        as {{ w }}_has_normal{{ "," if not loop.last }}
    {% endfor %}
from producing_years
left join indicators
    on indicators.municipality_id = producing_years.municipality_id
    and indicators.crop = producing_years.crop
    and indicators.harvest_year = producing_years.harvest_year
group by producing_years.municipality_id, producing_years.crop, producing_years.harvest_year
