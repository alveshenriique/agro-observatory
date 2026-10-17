-- Every window must be a run of consecutive months (possibly crossing the turn of the year):
-- ordering by year_offset * 12 + month, the span must equal the number of distinct months.
select
    crop,
    state_abbreviation,
    window_name,
    count(*) as months,
    max(year_offset * 12 + month) - min(year_offset * 12 + month) + 1 as span
from {{ ref('crop_calendar_windows') }}
group by crop, state_abbreviation, window_name
having max(year_offset * 12 + month) - min(year_offset * 12 + month) + 1 <> count(*)
    or count(distinct year_offset * 12 + month) <> count(*)
