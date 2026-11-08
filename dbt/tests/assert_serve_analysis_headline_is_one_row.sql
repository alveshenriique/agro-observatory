-- The main finding is a single row (the site and the README chart read it).
select row_count
from (select count(*) as row_count from {{ ref('serve_analysis_headline') }}) as counted
where row_count <> 1
