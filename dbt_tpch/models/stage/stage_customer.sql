select 
  c_custkey as customer_id
, c_name as customer_name
, c_phone as phone
, c_address as address
, c_mktsegment as market_segment
, c_nationkey as nation_id
from
    {{ source("main", "customer") }}