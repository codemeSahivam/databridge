# Data catalog — FILL THIS IN

Replace the example rows with your real tables. Keep it short: only tables people actually ask about.
Claude reads this before every query, so accuracy here matters more than completeness.

## Snowflake  (account: `<your-account>`, warehouse: `<ANALYTICS_WH>`)

| Table | What it is | Grain | Date / partition column | Freshness | Notes |
|---|---|---|---|---|---|
| `PROD.SALES.ORDERS` | All customer orders (example) | 1 row per order | `ORDER_DATE` | hourly | amounts in USD; exclude `STATUS = 'TEST'` |
| `PROD.SALES.CUSTOMERS` | Customer master (example) | 1 row per customer | `CREATED_AT` | daily 02:00 UTC | |
| `PROD.FINANCE.REVENUE_DAILY` | Finance-approved revenue (example) | day × region | `REVENUE_DATE` | daily 04:00 UTC | **source of truth for revenue** |

## Databricks  (workspace: `<your-workspace>.cloud.databricks.com`, catalog: `main`)

| Table | What it is | Grain | Date / partition column | Freshness | Notes |
|---|---|---|---|---|---|
| `main.features.customer_daily` | ML feature table (example) | customer × day | `ds` | daily | |
| `main.forecast.revenue_forecast` | Revenue forecast (example) | day × region | `forecast_date` | weekly Mon | compare with `REVENUE_DAILY` |
| `main.events.app_events` | Raw product events (example) | 1 row per event | `event_date` | 15 min | huge — always filter `event_date` |

## How the systems relate
- Example: `main.sales.orders` in Databricks is a nightly copy of Snowflake `PROD.SALES.ORDERS` (lags ~6h).
- Example: QuickSight datasets read Snowflake directly unless `dashboards.md` says otherwise.

## Off-limits
Tables blocked by the server (`BLOCKED_TABLE_PATTERNS`), e.g. anything in a `PII` schema. Don't suggest alternatives.
