---
name: company-data
description: How to answer questions, cross-check numbers, build QuickSight dashboards and write reports from the company's Snowflake, Databricks and QuickSight. Use for any question about company metrics, tables, dashboards or data discrepancies.
---

# Company data

You have the `databridge` MCP tools: read-only SQL on Snowflake and Databricks, QuickSight
read access, and confirm-gated QuickSight edits. This skill tells you *where* things live and
*what the numbers mean*. The reference files are the source of truth — read the one you need
before writing SQL, and never guess a table or metric definition.

| Need | Read |
|---|---|
| Which system / table holds what, grain, freshness | `reference/catalog.md` |
| How a metric is defined (revenue, active customer, churn, …) | `reference/metrics.md` |
| Which dashboard shows what, and which dataset feeds it | `reference/dashboards.md` |
| Snowflake vs Databricks SQL differences | `reference/sql-dialects.md` |

## Rules (always)

1. **Source of truth first.** Each metric in `metrics.md` names one system as its source of truth.
   Answer from that system; use the other only to cross-check.
2. **Aggregate in SQL.** Results are capped at a few hundred rows. Never pull raw rows to count them yourself.
3. **Always filter by date** on large fact tables (see `catalog.md` for partition columns).
4. **Show your work.** End every numeric answer with the system, table(s) and date range used, and the SQL in a collapsed block.
5. **Blocked data stays blocked.** If a tool says a table is blocked by policy, tell the user; don't look for a workaround table.
6. **Unknowns:** if a term isn't defined in `metrics.md`, say so and ask, rather than inventing a definition.

## Workflow: answer a data question
1. Map the question to a metric in `metrics.md` and its source-of-truth table in `catalog.md`.
2. If unsure of columns, call `*_describe_table` (cheap) before querying.
3. Write one aggregated query in the right dialect; run it.
4. Sanity-check: totals in a plausible range? Date range complete (check the max date)? If anything looks off, say so.
5. Answer in one or two sentences first, then the supporting table.

## Workflow: cross-check numbers between systems
1. Write the same metric for Snowflake and Databricks with **identical column aliases** and the same date range / grain.
2. Call `crosscheck_metric` with `key_columns` = the grain (e.g. `["order_date","region"]`), default tolerance 0.5 %.
3. For a dashboard number: `quicksight_describe_dashboard` → find the visual's dataset → `quicksight_describe_dataset`
   to see its source table/custom SQL → re-run that logic in the warehouse → compare. Also check
   `quicksight_dataset_refresh_status`; a stale SPICE refresh is the most common cause of a mismatch.
4. Report: MATCH / MISMATCH, the biggest differences, and the most likely cause (late data, timezone, filter, definition drift, stale SPICE).

## Workflow: build or change a QuickSight dashboard
1. Never edit production dashboards. Only ids allowed by the server (default prefix `claude-`) can be changed;
   for anything else, create a `claude-` copy.
2. Start from an existing definition (`quicksight_get_dashboard_definition`) of a similar dashboard listed in
   `dashboards.md` and modify it, rather than writing a definition from scratch.
3. Call the create/update tool **without** `confirm` → show the user the preview (added/removed/changed visuals) →
   only after a clear "yes", call again with `confirm=true`.
4. After creating, call `quicksight_describe_dashboard` to confirm it succeeded and give the user its id.
5. Dataset refreshes use SPICE capacity: same preview → confirm flow, and only when the user asks.

## Workflow: scheduled reports
Use the templates in `reports/` at the repo root. Same rules as above, plus: compare to the previous period,
flag any metric that moved more than the threshold in `metrics.md`, and run one cross-check on the headline number.
