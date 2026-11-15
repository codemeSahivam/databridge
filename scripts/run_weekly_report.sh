#!/usr/bin/env bash
# Run the weekly report headlessly (cron, GitHub Actions, or a CI runner with access to the warehouses).
#   crontab:  0 3 * * MON  cd /opt/databridge && ./scripts/run_weekly_report.sh
# Only read-only tools are allowed here, so the run can never edit dashboards.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p reports/out

READ_TOOLS="mcp__databridge__snowflake_query,mcp__databridge__snowflake_list_tables,mcp__databridge__snowflake_describe_table,\
mcp__databridge__databricks_query,mcp__databridge__databricks_list_tables,mcp__databridge__databricks_describe_table,\
mcp__databridge__crosscheck_metric,mcp__databridge__quicksight_list_dashboards,mcp__databridge__quicksight_describe_dashboard,\
mcp__databridge__quicksight_list_datasets,mcp__databridge__quicksight_describe_dataset,mcp__databridge__quicksight_dataset_refresh_status,\
Read,Write(reports/out/**),Task,Skill"

claude -p "$(cat reports/weekly-business-review.md)" \
  --mcp-config .mcp.json \
  --allowedTools "$READ_TOOLS" \
  --output-format text

# Optional: post the newest report to Slack
# curl -X POST -H 'Content-type: application/json' --data "{\"text\": $(jq -Rs . < "$(ls -t reports/out/*.md | head -1)")}" "$SLACK_WEBHOOK_URL"
