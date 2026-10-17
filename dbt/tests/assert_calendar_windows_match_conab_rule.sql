-- The soybean windows in the seed must follow the documented rule applied to the CONAB
-- transcription: critical = main planting months shifted by two; season = first planting
-- month to last harvest month; months before the turn of the year get year_offset -1 when
-- the cycle crosses it. Guards hand edits to crop_calendar_windows.csv.
with conab as (
    select * from {{ ref('conab_soybean_calendar') }}
),

expected as (
    select
        state_abbreviation,
        'critical' as window_name,
        ((planting_start_month - 1 + i + 2) % 12) + 1 as month,
        case
            when planting_start_month > harvest_end_month
                and ((planting_start_month - 1 + i + 2) % 12) + 1 >= planting_start_month
                then -1
            else 0
        end as year_offset
    from conab
    cross join generate_series(0, (planting_end_month - planting_start_month + 12) % 12) as s (i)

    union all

    select
        state_abbreviation,
        'season',
        ((planting_start_month - 1 + i) % 12) + 1,
        case
            when planting_start_month > harvest_end_month
                and ((planting_start_month - 1 + i) % 12) + 1 >= planting_start_month
                then -1
            else 0
        end
    from conab
    cross join generate_series(0, (harvest_end_month - planting_start_month + 12) % 12) as s (i)
),

actual as (
    select state_abbreviation, window_name, month, year_offset
    from {{ ref('crop_calendar_windows') }}
    where crop = 'soybean'
)

select 'missing_in_seed' as issue, * from (select * from expected except select * from actual) as missing
union all
select 'unexpected_in_seed' as issue, * from (select * from actual except select * from expected) as extra
