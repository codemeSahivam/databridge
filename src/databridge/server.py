"""databridge: one private MCP server for Snowflake, Databricks and QuickSight.

Run locally for Claude Code (stdio):      databridge-mcp
Run as a shared team endpoint (HTTP):     databridge-mcp --http --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import math
from decimal import Decimal
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import quicksight as qs
from .config import settings
from .sql_guard import UnsafeQueryError, guard
from .warehouses import WAREHOUSES, databricks, snowflake

INSTRUCTIONS = """Company data tools. Snowflake and Databricks are READ-ONLY (one SELECT per call, rows capped).
QuickSight can be read freely; creating/updating dashboards or refreshing datasets is a two-step action:
call once without confirm to get a preview, show it to the user, and only call with confirm=true after the
user approves. Only dashboards marked editable by the company can be changed. Load the company-data skill
for table locations, metric definitions and dashboard mappings before writing SQL."""

mcp = MCPServer("databridge", instructions=INSTRUCTIONS)

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)
OVERWRITE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True)


# --------------------------------------------------------------------------- helpers
def _out(payload: Any) -> str:
    text = json.dumps(payload, default=str, indent=1)
    limit = settings().max_response_chars
    if len(text) > limit:
        text = text[:limit] + f"\n... [response truncated at {limit} chars; narrow the query or select fewer columns]"
    return text


def _blocked(name: str) -> str | None:
    name = name.lower()
    for pat in settings().blocked_tables:
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(name.split(".")[-1], pat):
            return pat
    return None


async def _run_query(warehouse: str, sql: str) -> dict[str, Any]:
    s = settings()
    try:
        g = guard(sql, warehouse, s.max_rows, s.blocked_tables)
    except UnsafeQueryError as e:
        raise ToolError(str(e)) from e
    try:
        result = await WAREHOUSES[warehouse].execute(g.sql)
    except TimeoutError as e:
        raise ToolError(f"Query exceeded {s.query_timeout_s}s. Add filters (date range, partitions) or aggregate first.") from e
    except Exception as e:  # driver errors carry the useful SQL message
        raise ToolError(f"{warehouse} error: {e}") from e
    out = result.to_dict()
    out["tables"] = g.tables
    if result.truncated:
        out["note"] = f"Only the first {s.max_rows} rows are shown. Aggregate or filter for complete answers."
    return out


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float, Decimal)):
        f = float(v)
        return None if math.isnan(f) else f
    try:
        return float(str(v))
    except ValueError:
        return None


def _confirm_gate(action: str, confirm: bool, preview: dict[str, Any]) -> str | None:
    if confirm:
        return None
    return _out({
        "status": "PREVIEW_ONLY - nothing was changed",
        "action": action,
        "preview": preview,
        "next_step": "Show this preview to the user. If they approve, call the same tool again with confirm=true.",
    })


# --------------------------------------------------------------------------- Snowflake
@mcp.tool(name="snowflake_query", annotations=READ)
async def snowflake_query(
    sql: Annotated[str, Field(description="One read-only Snowflake SQL query (SELECT/WITH). Fully qualify tables: DB.SCHEMA.TABLE.")],
) -> str:
    """Run one read-only SQL query on the company Snowflake account and return rows as JSON.
    Rows are capped (MAX_ROWS); aggregate in SQL instead of pulling raw rows."""
    return _out(await _run_query("snowflake", sql))


@mcp.tool(name="snowflake_list_tables", annotations=READ)
async def snowflake_list_tables(
    database: Annotated[str, Field(description="Snowflake database, e.g. PROD")],
    schema: Annotated[str, Field(description="Schema in that database, e.g. SALES")],
) -> str:
    """List tables and views in a Snowflake schema (name, type, row count, comment)."""
    try:
        return _out((await snowflake.list_tables(database, schema)).to_dict())
    except Exception as e:
        raise ToolError(f"snowflake error: {e}") from e


@mcp.tool(name="snowflake_describe_table", annotations=READ)
async def snowflake_describe_table(
    database: Annotated[str, Field(description="Snowflake database, e.g. PROD")],
    schema: Annotated[str, Field(description="Schema, e.g. SALES")],
    table: Annotated[str, Field(description="Table or view name, e.g. ORDERS")],
) -> str:
    """Show the columns (name, type, nullable, comment) of a Snowflake table."""
    if pat := _blocked(f"{database}.{schema}.{table}"):
        raise ToolError(f"Table is blocked by company policy (pattern '{pat}').")
    try:
        return _out((await snowflake.describe_table(database, schema, table)).to_dict())
    except Exception as e:
        raise ToolError(f"snowflake error: {e}") from e


# --------------------------------------------------------------------------- Databricks
@mcp.tool(name="databricks_query", annotations=READ)
async def databricks_query(
    sql: Annotated[str, Field(description="One read-only Databricks SQL query (SELECT/WITH). Use catalog.schema.table names.")],
) -> str:
    """Run one read-only SQL query on the company Databricks SQL warehouse and return rows as JSON.
    Rows are capped (MAX_ROWS); aggregate in SQL instead of pulling raw rows."""
    return _out(await _run_query("databricks", sql))


@mcp.tool(name="databricks_list_tables", annotations=READ)
async def databricks_list_tables(
    catalog: Annotated[str, Field(description="Unity Catalog catalog, e.g. main")],
    schema: Annotated[str, Field(description="Schema in that catalog, e.g. features")],
) -> str:
    """List tables and views in a Databricks (Unity Catalog) schema."""
    try:
        return _out((await databricks.list_tables(catalog, schema)).to_dict())
    except Exception as e:
        raise ToolError(f"databricks error: {e}") from e


@mcp.tool(name="databricks_describe_table", annotations=READ)
async def databricks_describe_table(
    catalog: Annotated[str, Field(description="Catalog, e.g. main")],
    schema: Annotated[str, Field(description="Schema, e.g. features")],
    table: Annotated[str, Field(description="Table name, e.g. customer_daily")],
) -> str:
    """Show the columns (name, type, nullable, comment) of a Databricks table."""
    if pat := _blocked(f"{catalog}.{schema}.{table}"):
        raise ToolError(f"Table is blocked by company policy (pattern '{pat}').")
    try:
        return _out((await databricks.describe_table(catalog, schema, table)).to_dict())
    except Exception as e:
        raise ToolError(f"databricks error: {e}") from e


# --------------------------------------------------------------------------- cross-check
@mcp.tool(name="crosscheck_metric", annotations=READ)
async def crosscheck_metric(
    snowflake_sql: Annotated[str, Field(description="Read-only Snowflake query producing the metric")],
    databricks_sql: Annotated[str, Field(description="Read-only Databricks query producing the same metric with the SAME column aliases")],
    key_columns: Annotated[list[str], Field(description="Columns to match rows on, e.g. ['order_date','region']. Empty = compare row by row.")] = [],
    tolerance_pct: Annotated[float, Field(description="Allowed relative difference in percent before a value counts as a mismatch", ge=0, le=100)] = 0.5,
) -> str:
    """Run the same metric in Snowflake and Databricks and report where they disagree.
    Numeric columns with the same alias are compared; rows are matched on key_columns."""
    sf = await _run_query("snowflake", snowflake_sql)
    dbx = await _run_query("databricks", databricks_sql)

    def norm(rows):
        return [{k.lower(): v for k, v in r.items()} for r in rows]

    a, b = norm(sf["rows"]), norm(dbx["rows"])
    keys = [k.lower() for k in key_columns]
    shared = [c for c in (a[0].keys() if a else []) if b and c in b[0] and c not in keys]

    def keyed(rows):
        if not keys:
            return {(i,): r for i, r in enumerate(rows)}
        return {tuple(str(r.get(k)) for k in keys): r for r in rows}

    ka, kb = keyed(a), keyed(b)
    mismatches, compared = [], 0
    for key in sorted(ka.keys() & kb.keys(), key=str):
        for col in shared:
            x, y = _num(ka[key][col]), _num(kb[key][col])
            if x is None or y is None:
                continue
            compared += 1
            base = max(abs(x), abs(y)) or 1.0
            diff_pct = abs(x - y) / base * 100
            if diff_pct > tolerance_pct:
                mismatches.append({"key": dict(zip(keys or ["row"], key)), "column": col,
                                   "snowflake": x, "databricks": y, "diff_pct": round(diff_pct, 3)})
    return _out({
        "verdict": "MATCH" if not mismatches and ka.keys() == kb.keys() else "MISMATCH",
        "compared_values": compared,
        "compared_columns": shared,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:200],
        "only_in_snowflake": [dict(zip(keys or ["row"], k)) for k in list(ka.keys() - kb.keys())[:50]],
        "only_in_databricks": [dict(zip(keys or ["row"], k)) for k in list(kb.keys() - ka.keys())[:50]],
        "truncated_inputs": sf["truncated"] or dbx["truncated"],
    })


# --------------------------------------------------------------------------- QuickSight (read)
async def _qs(method: str, **kwargs) -> dict[str, Any]:
    try:
        return await qs.call(method, **kwargs)
    except Exception as e:
        raise ToolError(f"QuickSight {method} failed: {e}") from e


async def _paginate(method: str, key: str, max_results: int, **kwargs) -> list[dict]:
    items, token = [], None
    while len(items) < max_results:
        resp = await _qs(method, MaxResults=min(100, max_results), **({"NextToken": token} if token else {}), **kwargs)
        items.extend(resp.get(key, []))
        token = resp.get("NextToken")
        if not token:
            break
    return items[:max_results]


@mcp.tool(name="quicksight_list_dashboards", annotations=READ)
async def quicksight_list_dashboards(
    name_contains: Annotated[str, Field(description="Case-insensitive filter on dashboard name; empty = all")] = "",
    max_results: Annotated[int, Field(ge=1, le=1000)] = 200,
) -> str:
    """List QuickSight dashboards (id, name, last updated, published version, editable-by-Claude flag)."""
    items = await _paginate("list_dashboards", "DashboardSummaryList", 1000)
    needle = name_contains.lower()
    rows = [
        {"id": d["DashboardId"], "name": d.get("Name"), "last_updated": d.get("LastUpdatedTime"),
         "published_version": d.get("PublishedVersionNumber"), "editable_by_claude": qs.is_editable(d["DashboardId"])}
        for d in items if needle in (d.get("Name") or "").lower()
    ]
    return _out({"count": len(rows[:max_results]), "dashboards": rows[:max_results]})


@mcp.tool(name="quicksight_describe_dashboard", annotations=READ)
async def quicksight_describe_dashboard(
    dashboard_id: Annotated[str, Field(description="QuickSight dashboard id")],
) -> str:
    """Summarize a dashboard: sheets, visuals with titles, datasets it uses, version and whether Claude may edit it."""
    meta = (await _qs("describe_dashboard", DashboardId=dashboard_id))["Dashboard"]
    defn = (await _qs("describe_dashboard_definition", DashboardId=dashboard_id)).get("Definition", {})
    return _out({
        "id": dashboard_id, "name": meta.get("Name"),
        "version": meta.get("Version", {}).get("VersionNumber"),
        "status": meta.get("Version", {}).get("Status"),
        "dataset_arns": meta.get("Version", {}).get("DataSetArns", []),
        "editable_by_claude": qs.is_editable(dashboard_id), "edit_rule": qs.editable_rule(),
        "layout": qs.summarize_definition(defn),
    })


@mcp.tool(name="quicksight_get_dashboard_definition", annotations=READ)
async def quicksight_get_dashboard_definition(
    dashboard_id: Annotated[str, Field(description="QuickSight dashboard id")],
) -> str:
    """Return the full JSON definition of a dashboard. Use it as the starting point for quicksight_update_dashboard
    or as a template for quicksight_create_dashboard. Large dashboards may be truncated; prefer describe first."""
    resp = await _qs("describe_dashboard_definition", DashboardId=dashboard_id)
    return _out({"name": resp.get("Name"), "definition": resp.get("Definition")})


@mcp.tool(name="quicksight_list_datasets", annotations=READ)
async def quicksight_list_datasets(
    name_contains: Annotated[str, Field(description="Case-insensitive filter on dataset name; empty = all")] = "",
    max_results: Annotated[int, Field(ge=1, le=1000)] = 200,
) -> str:
    """List QuickSight datasets (id, name, ARN, import mode SPICE/DIRECT_QUERY)."""
    items = await _paginate("list_data_sets", "DataSetSummaries", 1000)
    needle = name_contains.lower()
    rows = [{"id": d["DataSetId"], "name": d.get("Name"), "arn": d.get("Arn"), "import_mode": d.get("ImportMode"),
             "last_updated": d.get("LastUpdatedTime")} for d in items if needle in (d.get("Name") or "").lower()]
    return _out({"count": len(rows[:max_results]), "datasets": rows[:max_results]})


@mcp.tool(name="quicksight_describe_dataset", annotations=READ)
async def quicksight_describe_dataset(
    dataset_id: Annotated[str, Field(description="QuickSight dataset id")],
) -> str:
    """Show where a dataset's data comes from (source tables / custom SQL), its columns and import mode.
    Use this to map a dashboard number back to Snowflake or Databricks tables."""
    ds = (await _qs("describe_data_set", DataSetId=dataset_id))["DataSet"]
    physical = {}
    for key, table in ds.get("PhysicalTableMap", {}).items():
        kind, body = next(iter(table.items()))
        physical[key] = {"kind": kind, "datasource_arn": body.get("DataSourceArn"),
                         "catalog": body.get("Catalog"), "schema": body.get("Schema"), "table": body.get("Name"),
                         "custom_sql": body.get("SqlQuery")}
    return _out({"id": dataset_id, "name": ds.get("Name"), "import_mode": ds.get("ImportMode"),
                 "physical_tables": physical,
                 "columns": [{"name": c.get("Name"), "type": c.get("Type")} for c in ds.get("OutputColumns", [])]})


@mcp.tool(name="quicksight_dataset_refresh_status", annotations=READ)
async def quicksight_dataset_refresh_status(
    dataset_id: Annotated[str, Field(description="QuickSight dataset id")],
    max_results: Annotated[int, Field(ge=1, le=50)] = 5,
) -> str:
    """Show the most recent SPICE refreshes (ingestions) of a dataset: status, rows, errors, timing."""
    resp = await _qs("list_ingestions", DataSetId=dataset_id, MaxResults=max_results)
    rows = [{"id": i.get("IngestionId"), "status": i.get("IngestionStatus"), "created": i.get("CreatedTime"),
             "seconds": i.get("IngestionTimeInSeconds"), "rows_ingested": i.get("RowInfo", {}).get("RowsIngested"),
             "rows_dropped": i.get("RowInfo", {}).get("RowsDropped"), "error": i.get("ErrorInfo", {}).get("Message")}
            for i in resp.get("Ingestions", [])]
    return _out({"dataset_id": dataset_id, "ingestions": rows})


# --------------------------------------------------------------------------- QuickSight (write, confirm-gated)
OWNER_ACTIONS = [
    "quicksight:DescribeDashboard", "quicksight:ListDashboardVersions", "quicksight:UpdateDashboardPermissions",
    "quicksight:QueryDashboard", "quicksight:UpdateDashboard", "quicksight:DeleteDashboard",
    "quicksight:DescribeDashboardPermissions", "quicksight:UpdateDashboardPublishedVersion",
]


def _parse_definition(definition_json: str) -> dict[str, Any]:
    try:
        defn = json.loads(definition_json)
    except json.JSONDecodeError as e:
        raise ToolError(f"definition_json is not valid JSON: {e}") from e
    if "definition" in defn and "Sheets" not in defn:  # accept the output of get_dashboard_definition as-is
        defn = defn["definition"]
    if not defn.get("DataSetIdentifierDeclarations") or not defn.get("Sheets"):
        raise ToolError("Definition needs 'DataSetIdentifierDeclarations' and at least one entry in 'Sheets'.")
    return defn


def _require_editable(dashboard_id: str) -> None:
    if not qs.is_editable(dashboard_id):
        raise ToolError(f"Dashboard '{dashboard_id}' is not editable by Claude ({qs.editable_rule()}). "
                        "Create a copy with an allowed id instead, or ask an admin to add it to QS_EDITABLE_DASHBOARD_IDS.")


@mcp.tool(name="quicksight_create_dashboard", annotations=WRITE)
async def quicksight_create_dashboard(
    dashboard_id: Annotated[str, Field(description="New dashboard id; must match the company's editable prefix, e.g. 'claude-weekly-revenue'")],
    name: Annotated[str, Field(description="Display name")],
    definition_json: Annotated[str, Field(description="Dashboard Definition JSON (Sheets, DataSetIdentifierDeclarations, ...)")],
    confirm: Annotated[bool, Field(description="false = preview only. true = actually create (only after the user approves the preview)")] = False,
) -> str:
    """Create a new QuickSight dashboard from a definition. Two-step: preview first, then confirm=true."""
    _require_editable(dashboard_id)
    defn = _parse_definition(definition_json)
    summary = qs.summarize_definition(defn)
    if gate := _confirm_gate("create_dashboard", confirm, {"dashboard_id": dashboard_id, "name": name, "layout": summary}):
        return gate
    kwargs: dict[str, Any] = dict(DashboardId=dashboard_id, Name=name, Definition=defn)
    if settings().qs_owner_arn:
        kwargs["Permissions"] = [{"Principal": settings().qs_owner_arn, "Actions": OWNER_ACTIONS}]
    resp = await _qs("create_dashboard", **kwargs)
    qs.audit("create_dashboard", dashboard_id=dashboard_id, name=name, version_arn=resp.get("VersionArn"))
    return _out({"status": resp.get("CreationStatus"), "arn": resp.get("Arn"), "version_arn": resp.get("VersionArn"),
                 "note": "Creation is async; call quicksight_describe_dashboard in a few seconds to confirm it is CREATION_SUCCESSFUL."})


@mcp.tool(name="quicksight_update_dashboard", annotations=OVERWRITE)
async def quicksight_update_dashboard(
    dashboard_id: Annotated[str, Field(description="Existing dashboard id that is marked editable")],
    definition_json: Annotated[str, Field(description="Complete new Definition JSON (start from quicksight_get_dashboard_definition)")],
    confirm: Annotated[bool, Field(description="false = show what would change. true = apply (only after the user approves)")] = False,
    publish: Annotated[bool, Field(description="Publish the new version so viewers see it immediately")] = True,
) -> str:
    """Replace an editable dashboard's definition with a new version (old versions stay in history).
    Two-step: first call returns a diff of sheets/visuals; call again with confirm=true to apply."""
    _require_editable(dashboard_id)
    new = _parse_definition(definition_json)
    current = await _qs("describe_dashboard_definition", DashboardId=dashboard_id)
    diff = qs.diff_summaries(qs.summarize_definition(current.get("Definition", {})), qs.summarize_definition(new))
    if gate := _confirm_gate("update_dashboard", confirm, {"dashboard_id": dashboard_id, "publish": publish, "changes": diff}):
        return gate
    resp = await _qs("update_dashboard", DashboardId=dashboard_id, Name=current.get("Name") or dashboard_id, Definition=new)
    version = qs.version_from_arn(resp["VersionArn"])
    if publish:
        await _qs("update_dashboard_published_version", DashboardId=dashboard_id, VersionNumber=version)
    qs.audit("update_dashboard", dashboard_id=dashboard_id, version=version, published=publish, changes=diff)
    return _out({"status": resp.get("CreationStatus"), "new_version": version, "published": publish,
                 "rollback": f"To roll back, publish the previous version with update_dashboard_published_version (version {version - 1})."})


@mcp.tool(name="quicksight_refresh_dataset", annotations=WRITE)
async def quicksight_refresh_dataset(
    dataset_id: Annotated[str, Field(description="SPICE dataset id to refresh")],
    confirm: Annotated[bool, Field(description="false = preview only. true = start the refresh (after the user approves)")] = False,
) -> str:
    """Start a SPICE refresh for a dataset (uses SPICE capacity). Two-step: preview, then confirm=true."""
    ds = (await _qs("describe_data_set", DataSetId=dataset_id))["DataSet"]
    if ds.get("ImportMode") != "SPICE":
        raise ToolError("This dataset is DIRECT_QUERY; it is always live and needs no refresh.")
    if gate := _confirm_gate("refresh_dataset", confirm, {"dataset_id": dataset_id, "name": ds.get("Name")}):
        return gate
    import uuid

    ingestion_id = f"claude-{uuid.uuid4().hex[:12]}"
    resp = await _qs("create_ingestion", DataSetId=dataset_id, IngestionId=ingestion_id, IngestionType="FULL_REFRESH")
    qs.audit("refresh_dataset", dataset_id=dataset_id, ingestion_id=ingestion_id)
    return _out({"ingestion_id": ingestion_id, "status": resp.get("IngestionStatus"),
                 "note": "Check progress with quicksight_dataset_refresh_status."})


# --------------------------------------------------------------------------- entrypoint
def main() -> None:
    p = argparse.ArgumentParser(description="DataBridge MCP server")
    p.add_argument("--http", action="store_true", help="Serve Streamable HTTP instead of stdio")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args()
    if args.http:
        mcp.run("streamable-http", host=args.host, port=args.port, stateless_http=True, json_response=True)
    else:
        mcp.run("stdio")


if __name__ == "__main__":
    main()
