select 
  n_nationkey as nation_id
, n_name as nation_name
, n_regionkey as region_id
from
    {{ source("main", "nation") }}