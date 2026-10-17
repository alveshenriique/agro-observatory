with source as (
    select * from {{ source('raw', 'brdwgd_municipality_cells') }}
)

select
    municipality_id,
    method as cell_method,
    cell_count,
    centroid_lon,
    centroid_lat,
    representative_lon,
    representative_lat,
    _source_version as source_version,
    _ingested_at as ingested_at,
    _loaded_at as loaded_at
from source
