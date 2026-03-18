select 
  customer_id
, customer_name
, phone
, address
, market_segment
, n.nation_name
from {{ ref("stage_customer") }} as c
 left join {{ ref("stage_nation") }} as n on n.nation_id = c.nation_id
