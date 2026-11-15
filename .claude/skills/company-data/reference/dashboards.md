# QuickSight dashboards — FILL THIS IN

| Dashboard (id) | Audience | What it shows | Dataset(s) → source | Owner | Editable by Claude? |
|---|---|---|---|---|---|
| Exec Revenue (`exec-revenue-prod`) — example | Leadership | Daily revenue by region | `revenue_daily_ds` → Snowflake `PROD.FINANCE.REVENUE_DAILY` (SPICE, refresh 05:00 UTC) | Finance BI | No — make a `claude-` copy |
| Forecast vs Actual (`forecast-vs-actual`) — example | FP&A | Forecast accuracy | `forecast_ds` → Databricks `main.forecast.revenue_forecast` (direct query) | Data Science | No |
| Claude sandbox (`claude-*`) | Anyone | Dashboards Claude builds on request | any | requester | Yes |

## Conventions for new dashboards
- Id: `claude-<team>-<topic>`, e.g. `claude-sales-weekly-pipeline`
- Name: start with "[Draft]" until a human owner promotes it
- Reuse existing datasets; don't create new datasets (ask the BI team)
- Template to copy from: `<id of your best-looking dashboard>`
