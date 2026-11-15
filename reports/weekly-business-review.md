Use the data-analyst agent and the company-data skill to write this week's business review.

Period: the last complete Monday–Sunday week (UTC), compared with the week before and the same week last year.

1. For every metric in reference/metrics.md: value this week, previous week, % change, and same week last year.
   Use each metric's source of truth.
2. Flag every metric whose week-over-week change is beyond its alert threshold, and give the top 1–2 drivers
   (break it down by region / product / channel, whichever explains most of the change).
3. Cross-check the headline revenue number between Snowflake and Databricks with crosscheck_metric, and check the
   refresh status of the datasets behind the dashboards listed in reference/dashboards.md. Report any mismatch or
   stale refresh.
4. Do NOT create or change any dashboard and do NOT refresh datasets in this run.

Output: a markdown report with a 3-bullet summary at the top, then a metrics table, then flags, then data-quality notes.
Save it to reports/out/weekly-<YYYY-MM-DD>.md.
