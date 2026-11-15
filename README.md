# DataBridge

A private bridge between Claude and your company's **Snowflake**, **Databricks** and **QuickSight**: ask data questions in plain English, cross-check numbers between systems, build dashboards and get scheduled reports.

A private, company-only setup that lets your team ask Claude about data in **Snowflake**, **Databricks** and **QuickSight**:

| Piece | Where | What it does |
|---|---|---|
| **MCP server** (`databridge`) | `src/` | The connection. 16 tools: read-only SQL on both warehouses, schema browsing, cross-system checks, QuickSight read access, and confirm-gated dashboard edits. |
| **Skill** (`company-data`) | `.claude/skills/company-data/` | The company knowledge: where tables live, how metrics are defined, which dashboards use which datasets, and the rules Claude follows. |
| **Agent** (`data-analyst`) | `.claude/agents/data-analyst.md` | A delegated analyst for multi-step jobs such as investigations, dashboard builds and reports. |
| **Scheduled report** | `reports/`, `scripts/` | A weekly business review that runs headlessly with read-only tools. |

## Safety model

- **SQL is read-only on two levels:** the database identities are read-only, and every query is parsed by `sql_guard.py`. Only a single SELECT, WITH or DESCRIBE statement is allowed. Rows are always capped, and tables matching `BLOCKED_TABLE_PATTERNS` are rejected.
- **QuickSight edits are limited and two-step.** Only dashboards whose id starts with `claude-` (or that are allow-listed) can be changed. Every write first returns a preview, and nothing changes until it is called again with `confirm=true`. Claude Code also asks for permission (`.claude/settings.json`). Every write is logged to `audit.log.jsonl`. Updates create a new dashboard version, so you can always roll back.
- **Scheduled runs** get only the read tools.

## Setup (about an hour)

### 1. Create read-only identities

**Snowflake** (run as SECURITYADMIN or another role with privileges to create roles and users):
```sql
CREATE ROLE CLAUDE_READONLY;
GRANT USAGE ON WAREHOUSE ANALYTICS_XS_WH TO ROLE CLAUDE_READONLY;
GRANT USAGE ON DATABASE PROD TO ROLE CLAUDE_READONLY;
-- repeat for each approved schema; never grant PII/HR schemas
GRANT USAGE ON SCHEMA PROD.SALES TO ROLE CLAUDE_READONLY;
GRANT SELECT ON ALL TABLES IN SCHEMA PROD.SALES TO ROLE CLAUDE_READONLY;
GRANT SELECT ON ALL VIEWS IN SCHEMA PROD.SALES TO ROLE CLAUDE_READONLY;
GRANT SELECT ON FUTURE TABLES IN SCHEMA PROD.SALES TO ROLE CLAUDE_READONLY;
CREATE USER SVC_CLAUDE_READONLY TYPE = SERVICE DEFAULT_ROLE = CLAUDE_READONLY RSA_PUBLIC_KEY = '<public key>';
GRANT ROLE CLAUDE_READONLY TO USER SVC_CLAUDE_READONLY;
```
To have each person query as themselves instead, skip the service user and set `SNOWFLAKE_AUTHENTICATOR=externalbrowser`.

**Databricks:** create a service principal, give it *Can use* on one SQL warehouse, and grant `USE CATALOG`, `USE SCHEMA` and `SELECT` only on the schemas Claude may read (Unity Catalog). Then create an OAuth secret for it.

**QuickSight (IAM):** attach this policy to the role or profile the server uses:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": [
        "quicksight:ListDashboards", "quicksight:DescribeDashboard", "quicksight:DescribeDashboardDefinition",
        "quicksight:ListDataSets", "quicksight:DescribeDataSet", "quicksight:ListIngestions"],
      "Resource": "*" },
    { "Effect": "Allow", "Action": [
        "quicksight:CreateDashboard", "quicksight:UpdateDashboard", "quicksight:UpdateDashboardPublishedVersion"],
      "Resource": "arn:aws:quicksight:*:<ACCOUNT_ID>:dashboard/claude-*" },
    { "Effect": "Allow", "Action": ["quicksight:CreateIngestion", "quicksight:PassDataSet"],
      "Resource": ["arn:aws:quicksight:*:<ACCOUNT_ID>:dataset/*", "arn:aws:quicksight:*:<ACCOUNT_ID>:dataset/*/ingestion/*"] }
  ]
}
```
The `dashboard/claude-*` resource means AWS enforces the edit limit too, not just the server.

### 2. Install and configure
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # fill in your values
pytest                      # 25 offline tests: guard, tool surface, QuickSight gating, cross-check
npx @modelcontextprotocol/inspector databridge-mcp   # try the tools against your real systems
```

### 3. Teach it your company (the most important step)
Fill in the three files in `.claude/skills/company-data/reference/`:
- `catalog.md`: your real tables, grain, date columns and freshness
- `metrics.md`: your metric definitions, the source of truth for each, and alert thresholds
- `dashboards.md`: your dashboards, their datasets and owners

The examples in these files show the format. Ten well-described tables are better than 200 undocumented ones.

### 4. Use it with your team (Claude Code)
Commit this repo, minus `.env`. Each teammate clones it, does step 2, and runs `claude` in the repo folder. The server, skill, agent and permissions all load automatically. Try:
- "What was revenue by region last week?"
- "Why does the Exec Revenue dashboard show a different number from Snowflake for October?"
- "Use the data-analyst agent to build a claude-sales-weekly dashboard like exec-revenue-prod, but by channel."

To make the skill available in Claude chat as well, zip `.claude/skills/company-data/` and upload it as a skill (or have your org admin provision it for everyone).

### 5. Scheduled weekly report
On a machine that has access to the warehouses and Claude Code installed:
```bash
chmod +x scripts/run_weekly_report.sh
crontab -e   # 0 3 * * MON  cd /opt/databridge && ./scripts/run_weekly_report.sh
```
Reports are saved to `reports/out/`. Uncomment the Slack line in the script to post them to Slack.

## Optional: a shared server for claude.ai
`databridge-mcp --http --host 0.0.0.0 --port 8000` serves the same tools over Streamable HTTP (at `/mcp`). This mode has **no authentication of its own**, so deploy it only inside your network, behind your company's OAuth/SSO gateway. An org admin can then add it as a custom connector in claude.ai, and the whole team gets it in chat without any local setup.

## Extending
Add a tool by writing one decorated function in `server.py`. Use `annotations=READ` for read-only tools. Any write should use `_confirm_gate` and `qs.audit`.
