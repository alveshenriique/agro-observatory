-- The soybean windows in the seed must follow the documented rule applied to the CONAB
-- transcription: critical = main planting months shifted by two; season = first planting
-- month to last harvest month; months before the turn of the year get year_offset -1 when
-- the cycle crosses it. Guards hand edits to crop_calendar_windows.csv.
with conab as (
    select * from {{ ref('conab_soybean_calendar') }}
),

-- Offsets 0..11 from the first planting month; each window keeps the ones within its span.
offsets as (
    select cast(generated_number - 1 as {{ dbt.type_int() }}) as i
    from ({{ dbt_utils.generate_series(12) }}) as numbers
),

expected as (
    select
        conab.state_abbreviation,
        'critical' as window_name,
        mod(conab.planting_start_month - 1 + offsets.i + 2, 12) + 1 as month,
        case
            when conab.planting_start_month > conab.harvest_end_month
                and mod(conab.planting_start_month - 1 + offsets.i + 2, 12) + 1 >= conab.planting_start_month
                then -1
            else 0
        end as year_offset
    from conab
    cross join offsets
    where offsets.i <= mod(conab.planting_end_month - conab.planting_start_month + 12, 12)

    union all

    select
        conab.state_abbreviation,
        'season',
        mod(conab.planting_start_month - 1 + offsets.i, 12) + 1,
        case
            when conab.planting_start_month > conab.harvest_end_month
                and mod(conab.planting_start_month - 1 + offsets.i, 12) + 1 >= conab.planting_start_month
                then -1
            else 0
        end
    from conab
    cross join offsets
    where offsets.i <= mod(conab.harvest_end_month - conab.planting_start_month + 12, 12)
),

actual as (
    select state_abbreviation, window_name, month, year_offset
    from {{ ref('crop_calendar_windows') }}
    where crop = 'soybean'
),

missing as (
    select * from expected
    {{ dbt.except() }}
    select * from actual
),

extra as (
    select * from actual
    {{ dbt.except() }}
    select * from expected
)

select 'missing_in_seed' as issue, missing.* from missing
union all
select 'unexpected_in_seed' as issue, extra.* from extra
