import asyncio
import json

import pytest

from databridge import quicksight as qs
from databridge import server
from databridge.sql_guard import UnsafeQueryError, guard
from databridge.warehouses import QueryResult

BLOCK = ["*.pii.*", "salaries"]


# ---------------------------------------------------------------- SQL guard
@pytest.mark.parametrize("dialect", ["snowflake", "databricks"])
@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "select region, sum(amount) from prod.sales.orders group by 1",
    "WITH x AS (SELECT * FROM prod.sales.orders) SELECT count(*) FROM x",
    "SELECT a FROM t1 UNION ALL SELECT a FROM t2",
    "SELECT * FROM prod.sales.orders LIMIT 100000;",
])
def test_allows_reads_and_caps_rows(sql, dialect):
    g = guard(sql, dialect, 500, BLOCK)
    assert "LIMIT 501" in g.sql.upper()


@pytest.mark.parametrize("sql", [
    "DELETE FROM prod.sales.orders",
    "UPDATE prod.sales.orders SET amount = 0",
    "INSERT INTO t SELECT * FROM s",
    "DROP TABLE prod.sales.orders",
    "CREATE TABLE x AS SELECT 1",
    "MERGE INTO t USING s ON t.id = s.id WHEN MATCHED THEN DELETE",
    "SELECT 1; DROP TABLE x",
    "GRANT SELECT ON TABLE t TO ROLE r",
    "TRUNCATE TABLE t",
    "",
])
def test_blocks_writes(sql):
    with pytest.raises(UnsafeQueryError):
        guard(sql, "snowflake", 500, BLOCK)


def test_blocks_policy_tables_but_not_ctes():
    with pytest.raises(UnsafeQueryError, match="blocked"):
        guard("SELECT * FROM prod.pii.customers", "snowflake", 500, BLOCK)
    with pytest.raises(UnsafeQueryError, match="blocked"):
        guard("SELECT * FROM hr.core.salaries", "databricks", 500, BLOCK)
    # a CTE that happens to share a blocked name is fine
    guard("WITH salaries AS (SELECT 1 AS a) SELECT * FROM salaries", "snowflake", 500, BLOCK)


# ---------------------------------------------------------------- tool surface
def test_tools_registered_with_annotations():
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    expected = {
        "snowflake_query", "snowflake_list_tables", "snowflake_describe_table",
        "databricks_query", "databricks_list_tables", "databricks_describe_table", "crosscheck_metric",
        "quicksight_list_dashboards", "quicksight_describe_dashboard", "quicksight_get_dashboard_definition",
        "quicksight_list_datasets", "quicksight_describe_dataset", "quicksight_dataset_refresh_status",
        "quicksight_create_dashboard", "quicksight_update_dashboard", "quicksight_refresh_dataset",
    }
    assert expected <= tools.keys()
    assert tools["snowflake_query"].annotations.read_only_hint is True
    assert tools["quicksight_update_dashboard"].annotations.destructive_hint is True


# ---------------------------------------------------------------- QuickSight gating
DEFN = {
    "DataSetIdentifierDeclarations": [{"Identifier": "orders", "DataSetArn": "arn:x"}],
    "Sheets": [{"SheetId": "s1", "Name": "Overview", "Visuals": [
        {"KPIVisual": {"VisualId": "v1", "Title": {"FormatText": {"PlainText": "Revenue"}}}}]}],
}


@pytest.fixture
def fake_qs(monkeypatch, tmp_path):
    calls = []

    async def fake_call(method, **kw):
        calls.append(method)
        if method == "describe_dashboard_definition":
            return {"Name": "Weekly", "Definition": DEFN}
        if method == "update_dashboard":
            return {"VersionArn": "arn:aws:quicksight:us-east-1:1:dashboard/claude-weekly/version/7", "CreationStatus": "CREATION_IN_PROGRESS"}
        return {}

    monkeypatch.setattr(qs, "call", fake_call)
    monkeypatch.setattr(qs, "audit", lambda *a, **k: calls.append("AUDIT"))
    return calls


def test_update_requires_editable_id(fake_qs):
    with pytest.raises(Exception, match="not editable"):
        asyncio.run(server.quicksight_update_dashboard("finance-prod", json.dumps(DEFN), confirm=True))
    assert fake_qs == []


def test_update_previews_then_applies(fake_qs):
    new = json.loads(json.dumps(DEFN))
    new["Sheets"][0]["Visuals"].append({"BarChartVisual": {"VisualId": "v2", "Title": {"FormatText": {"PlainText": "By region"}}}})

    preview = json.loads(asyncio.run(server.quicksight_update_dashboard("claude-weekly", json.dumps(new))))
    assert preview["status"].startswith("PREVIEW_ONLY")
    assert preview["preview"]["changes"]["added_visuals"] == ["[Overview] BarChartVisual: By region"]
    assert "update_dashboard" not in fake_qs

    done = json.loads(asyncio.run(server.quicksight_update_dashboard("claude-weekly", json.dumps(new), confirm=True)))
    assert done["new_version"] == 7
    assert fake_qs[-3:] == ["update_dashboard", "update_dashboard_published_version", "AUDIT"]


# ---------------------------------------------------------------- cross-check
def test_crosscheck_flags_mismatch(monkeypatch):
    data = {
        "snowflake": [{"REGION": "EU", "REVENUE": 100.0}, {"REGION": "US", "REVENUE": 200.0}],
        "databricks": [{"region": "EU", "revenue": 100.2}, {"region": "US", "revenue": 230.0}],
    }

    async def fake_exec(self, sql, params=None, max_rows=None):
        rows = data[self.name]
        return QueryResult(list(rows[0].keys()), rows, False)

    from databridge import warehouses
    monkeypatch.setattr(warehouses._Base, "execute", fake_exec)
    out = json.loads(asyncio.run(server.crosscheck_metric(
        "select region, sum(x) revenue from a group by 1", "select region, sum(x) revenue from b group by 1",
        key_columns=["region"], tolerance_pct=0.5)))
    assert out["verdict"] == "MISMATCH"
    assert [m["key"]["region"] for m in out["mismatches"]] == ["US"]
