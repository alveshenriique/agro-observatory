-- Climate indicators per municipality × crop × harvest year × calendar window, computed from
-- the daily grid for producing municipalities only. Long format: one row per window; the
-- fact pivots it. Indicators are null when the window has less than
-- `climate_min_window_coverage` of its days with data (series edges, CI sample).
-- The whole daily series of ~3,600 municipalities is scanned once; the pre-hook gives the
-- sorts of the dry-spell calculation enough memory to avoid spilling to disk.
{{ config(materialized='table', pre_hook="set work_mem = '512MB'") }}

{% set first_year = var('climate_first_harvest_year') %}
{% set min_coverage = var('climate_min_window_coverage') %}
{% set indicators = [
    'precipitation_mm', 'eto_mm', 'water_balance_mm', 'tmax_mean_c', 'tmax_max_c',
    'tmin_mean_c', 'tmin_min_c', 'hot_days', 'severe_hot_days', 'dry_days',
    'frost_days', 'severe_frost_days',
] %}

with calendar as (
    select crop, state_abbreviation, window_name, month, year_offset
    from {{ ref('crop_calendar_windows') }}
),

producing as (
    select municipality_id, crop, state_abbreviation
    from {{ ref('int_climate__producing_municipalities') }}
),

daily as (
    select * from {{ ref('stg_brdwgd__municipality_daily') }}
),

bounds as (
    select max(extract(year from date))::integer as last_harvest_year
    from daily
),

-- Each day of each producing municipality, assigned to every window that contains its
-- month (a day can belong to the soybean critical and season windows at once).
assigned as (
    select
        daily.municipality_id,
        producing.crop,
        producing.state_abbreviation,
        calendar.window_name,
        extract(year from daily.date)::integer - calendar.year_offset as harvest_year,
        daily.date,
        daily.precipitation_mm,
        daily.eto_mm,
        daily.tmax_c,
        daily.tmin_c,
        daily.precipitation_mm < {{ var('dry_day_precipitation_mm') }} as is_dry
    from daily
    inner join producing
        on producing.municipality_id = daily.municipality_id
    inner join calendar
        on calendar.crop = producing.crop
        and calendar.state_abbreviation = producing.state_abbreviation
        and calendar.month = extract(month from daily.date)::integer
    cross join bounds
    where extract(year from daily.date)::integer - calendar.year_offset
        between {{ first_year }} and bounds.last_harvest_year
),

-- Consecutive dry days form islands: the date minus the dry day's sequence number is
-- constant within a run (gaps-and-islands).
dry_runs as (
    select municipality_id, crop, window_name, harvest_year, island, count(*) as run_days
    from (
        select
            municipality_id,
            crop,
            window_name,
            harvest_year,
            date - (row_number() over (
                partition by municipality_id, crop, window_name, harvest_year
                order by date
            ))::integer as island
        from assigned
        where is_dry
    ) as dry_day_islands
    group by municipality_id, crop, window_name, harvest_year, island
),

longest_dry_spell as (
    select municipality_id, crop, window_name, harvest_year, max(run_days) as longest_dry_spell_days
    from dry_runs
    group by municipality_id, crop, window_name, harvest_year
),

aggregated as (
    select
        municipality_id,
        crop,
        state_abbreviation,
        window_name,
        harvest_year,
        count(*) filter (
            where precipitation_mm is not null and eto_mm is not null
                and tmax_c is not null and tmin_c is not null
        ) as days_with_data,
        sum(precipitation_mm) as precipitation_mm,
        sum(eto_mm) as eto_mm,
        sum(precipitation_mm - eto_mm) as water_balance_mm,
        avg(tmax_c) as tmax_mean_c,
        max(tmax_c) as tmax_max_c,
        avg(tmin_c) as tmin_mean_c,
        min(tmin_c) as tmin_min_c,
        count(*) filter (where tmax_c >= {{ var('heat_tmax_threshold_c') }}) as hot_days,
        count(*) filter (where tmax_c >= {{ var('severe_heat_tmax_threshold_c') }}) as severe_hot_days,
        count(*) filter (where is_dry) as dry_days,
        count(*) filter (where tmin_c <= {{ var('frost_tmin_threshold_c') }}) as frost_days,
        count(*) filter (where tmin_c <= {{ var('severe_frost_tmin_threshold_c') }}) as severe_frost_days
    from assigned
    group by municipality_id, crop, state_abbreviation, window_name, harvest_year
),

-- Calendar days each window has in each harvest year (months differ in length, and
-- February in leap years), so coverage can be checked without a date spine.
expected_days as (
    select
        calendar.crop,
        calendar.state_abbreviation,
        calendar.window_name,
        years.harvest_year,
        sum(extract(day from (
            make_date(years.harvest_year + calendar.year_offset, calendar.month, 1)
            + interval '1 month - 1 day'
        )))::integer as days_in_window
    from calendar
    cross join bounds
    cross join generate_series({{ first_year }}, bounds.last_harvest_year) as years (harvest_year)
    group by calendar.crop, calendar.state_abbreviation, calendar.window_name, years.harvest_year
)

select
    aggregated.municipality_id,
    aggregated.crop,
    aggregated.state_abbreviation,
    aggregated.window_name,
    aggregated.harvest_year,
    expected_days.days_in_window,
    aggregated.days_with_data,
    round(aggregated.days_with_data::numeric / expected_days.days_in_window, 4) as coverage,
    {% for indicator in indicators %}
    case
        when aggregated.days_with_data::numeric / expected_days.days_in_window >= {{ min_coverage }}
            then aggregated.{{ indicator }}
    end as {{ indicator }},
    {% endfor %}
    case
        when aggregated.days_with_data::numeric / expected_days.days_in_window >= {{ min_coverage }}
            then coalesce(longest_dry_spell.longest_dry_spell_days, 0)
    end as longest_dry_spell_days
from aggregated
inner join expected_days
    on expected_days.crop = aggregated.crop
    and expected_days.state_abbreviation = aggregated.state_abbreviation
    and expected_days.window_name = aggregated.window_name
    and expected_days.harvest_year = aggregated.harvest_year
left join longest_dry_spell
    on longest_dry_spell.municipality_id = aggregated.municipality_id
    and longest_dry_spell.crop = aggregated.crop
    and longest_dry_spell.window_name = aggregated.window_name
    and longest_dry_spell.harvest_year = aggregated.harvest_year
