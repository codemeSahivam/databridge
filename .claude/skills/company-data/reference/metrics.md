# Metric definitions — FILL THIS IN

One entry per metric. "Source of truth" is the system Claude answers from; the other is for cross-checks.
"Alert threshold" is used by scheduled reports to flag big moves.

## Revenue  (example)
- **Definition:** sum of `NET_AMOUNT_USD` for orders with `STATUS IN ('COMPLETED','SHIPPED')`, excluding test orders.
- **Source of truth:** Snowflake `PROD.FINANCE.REVENUE_DAILY.REVENUE_USD`
- **Cross-check:** Databricks `main.sales.orders` (expect ≤0.5 % difference; same-day data lags)
- **Timezone:** UTC days
- **Alert threshold:** ±10 % week over week

```sql
-- Snowflake reference query
SELECT revenue_date, region, SUM(revenue_usd) AS revenue
FROM PROD.FINANCE.REVENUE_DAILY
WHERE revenue_date BETWEEN :start AND :end
GROUP BY 1, 2
```

## Active customers  (example)
- **Definition:** distinct customers with ≥1 completed order in the trailing 90 days.
- **Source of truth:** Snowflake `PROD.SALES.ORDERS`
- **Alert threshold:** ±5 % week over week

## Add your metrics below
<!-- Copy the block above for each metric your team uses: churn, AOV, CAC, forecast accuracy, ... -->
