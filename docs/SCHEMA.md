# Chimera Data Schema (contract v1.0)

### Data Shapes (contrat v1.0)

AggregatedItem
```
title str
price {value float, currency str}
source str
epid str?
start_date str?
end_date str?
photo_url str?
link str
```

EpidStats
```
epid str
brand str?
model str?
total_items int
currency str
median_price float
q1_price float
q2_price float
q3_price float
q4_price float
avg_sell_days float?
sell_days_sample int
last_updated str
```

FlipScoreResponse
```
decision BUY|OFFER|SKIP
confidence float (0-1)
price_ratio float
margin_eur float
margin_pct float
velocity_flag fast|normal|slow|unknown
reasoning str
```

NavigatorRunResponse
```
query str
pipeline_ms int
probe_risk float
total_scraped int
total_scored int
deals list
summary str
```

DashboardResponse
```
bridge {version, uptime_seconds, status}
jobs {queued, active, failed_last_hour}
scraping {total_items, epids_tracked, last_scrape}
scoring {total_scored, deals_buy, deals_offer, deals_skip}
profiles {creating, warming, ready, senior, recycle}
proxy {residential_configured bool}
```

StealthRunResponse
```
run_id str
status success|error|captcha_blocked
security {waf, captcha, difficulty, proxy_recommendation}
result {http_status, html_len, items_count, duration_ms}
report {json_url, csv_url}
```

### SQLite Tables

risk_events
```
job_id
url
domain
risk_score
vendors_detected
ts
```

profiles
```
profile_id
geo_id
proxy_country
ua_profile_id
status (creating/warming/ready/senior/recycle)
age_days
created_at
last_active
warmed
cookies_count
```

epid_stats
```
epid
brand
model
total_items
currency
median_price
q1_price
q2_price
q3_price
q4_price
avg_sell_days
sell_days_sample
last_updated
```

scraped_items
```
id
epid
title
price_value
price_currency
start_date
end_date
source
url
scraped_at
```

stealth_runs
```
run_id
created_at
url
query
source
status
duration_ms
security_map
config_used
http_status
html_len
items_count
items_json
raw_markdown
report_path
error_msg
agent_id
ingest_done
```

### Nullability Rules
- Jamais un champ absent du JSON — toujours `null` si inconnu.
- avg_sell_days null jusqu'en prod avec WatchCount résidentiel.
- epid null sur 84% des items eBay.fr.
- end_date toujours null depuis eBay Browse API.
