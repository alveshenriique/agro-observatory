-- Both regional divisions must place a municipality in the same state.
select municipality_id, state_id, mesoregion_state_id
from {{ ref('stg_ibge__localities') }}
where mesoregion_state_id is not null
  and mesoregion_state_id <> state_id
