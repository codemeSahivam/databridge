"""Thin, read-only clients for Snowflake and Databricks SQL.

Connections are opened lazily and reused. All blocking driver calls run in a
worker thread so the MCP event loop stays responsive.
"""

from __future__ import annotations

import asyncio
import re
import threading
from dataclasses import dataclass
from typing import Any

from .config import settings

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def check_ident(value: str, what: str) -> str:
    if not value or not _IDENT.match(value):
        raise ValueError(f"Invalid {what} '{value}'. Use a plain identifier like SALES or analytics_prod.")
    return value


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    truncated: bool

    def to_dict(self) -> dict[str, Any]:
        return {"columns": self.columns, "row_count": len(self.rows), "truncated": self.truncated, "rows": self.rows}


def _rows(cursor, max_rows: int) -> QueryResult:
    cols = [d[0] for d in (cursor.description or [])]
    raw = cursor.fetchmany(max_rows + 1)
    truncated = len(raw) > max_rows
    return QueryResult(cols, [dict(zip(cols, r)) for r in raw[:max_rows]], truncated)


class _Base:
    name = "base"

    def __init__(self) -> None:
        self._conn = None
        self._lock = threading.Lock()

    def _connect(self):  # pragma: no cover - needs real credentials
        raise NotImplementedError

    def _conn_or_connect(self):
        with self._lock:
            if self._conn is None:
                self._conn = self._connect()
            return self._conn

    def _execute_sync(self, sql: str, params: Any | None, max_rows: int) -> QueryResult:
        conn = self._conn_or_connect()
        cur = conn.cursor()
        try:
            cur.execute(sql, params) if params is not None else cur.execute(sql)
            return _rows(cur, max_rows)
        finally:
            cur.close()

    async def execute(self, sql: str, params: Any | None = None, max_rows: int | None = None) -> QueryResult:
        s = settings()
        return await asyncio.wait_for(
            asyncio.to_thread(self._execute_sync, sql, params, max_rows or s.max_rows),
            timeout=s.query_timeout_s + 10,
        )


class Snowflake(_Base):
    name = "snowflake"

    def _connect(self):  # pragma: no cover - needs real credentials
        import snowflake.connector

        s = settings()
        if not (s.sf_account and s.sf_user):
            raise RuntimeError("Snowflake is not configured: set SNOWFLAKE_ACCOUNT and SNOWFLAKE_USER.")
        kwargs: dict[str, Any] = dict(
            account=s.sf_account,
            user=s.sf_user,
            role=s.sf_role or None,
            warehouse=s.sf_warehouse or None,
            database=s.sf_database or None,
            schema=s.sf_schema or None,
            application="databridge-mcp",
            session_parameters={
                "QUERY_TAG": "claude-databridge-mcp",
                "STATEMENT_TIMEOUT_IN_SECONDS": s.query_timeout_s,
            },
        )
        if s.sf_private_key_file:  # key-pair auth (recommended for service users)
            from cryptography.hazmat.primitives import serialization

            with open(s.sf_private_key_file, "rb") as f:
                key = serialization.load_pem_private_key(
                    f.read(), password=s.sf_private_key_passphrase.encode() if s.sf_private_key_passphrase else None
                )
            kwargs["private_key"] = key.private_bytes(
                serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        elif s.sf_authenticator:  # e.g. "externalbrowser" for per-person SSO
            kwargs["authenticator"] = s.sf_authenticator
        else:
            raise RuntimeError("Set SNOWFLAKE_PRIVATE_KEY_FILE (service user) or SNOWFLAKE_AUTHENTICATOR=externalbrowser (SSO).")
        return snowflake.connector.connect(**{k: v for k, v in kwargs.items() if v is not None})

    async def list_tables(self, database: str, schema: str) -> QueryResult:
        db = check_ident(database, "database")
        sql = (
            f"SELECT table_name, table_type, row_count, comment FROM {db}.INFORMATION_SCHEMA.TABLES "
            "WHERE table_schema = %s ORDER BY table_name"
        )
        return await self.execute(sql, (schema.upper(),), max_rows=1000)

    async def describe_table(self, database: str, schema: str, table: str) -> QueryResult:
        db = check_ident(database, "database")
        sql = (
            f"SELECT column_name, data_type, is_nullable, comment FROM {db}.INFORMATION_SCHEMA.COLUMNS "
            "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position"
        )
        return await self.execute(sql, (schema.upper(), table.upper()), max_rows=1000)


class Databricks(_Base):
    name = "databricks"

    def _connect(self):  # pragma: no cover - needs real credentials
        from databricks import sql as dbsql

        s = settings()
        if not (s.dbx_host and s.dbx_http_path):
            raise RuntimeError("Databricks is not configured: set DATABRICKS_HOST and DATABRICKS_HTTP_PATH.")
        kwargs: dict[str, Any] = dict(
            server_hostname=s.dbx_host,
            http_path=s.dbx_http_path,
            user_agent_entry="databridge-mcp",
            session_configuration={"STATEMENT_TIMEOUT": str(s.query_timeout_s)},
        )
        if s.dbx_client_id and s.dbx_client_secret:  # OAuth M2M service principal (recommended)
            from databricks.sdk.core import Config, oauth_service_principal

            cfg = Config(host=f"https://{s.dbx_host}", client_id=s.dbx_client_id, client_secret=s.dbx_client_secret)
            kwargs["credentials_provider"] = lambda: oauth_service_principal(cfg)
        elif s.dbx_token:
            kwargs["access_token"] = s.dbx_token
        else:
            raise RuntimeError("Set DATABRICKS_CLIENT_ID + DATABRICKS_CLIENT_SECRET (service principal) or DATABRICKS_TOKEN.")
        return dbsql.connect(**kwargs)

    async def list_tables(self, catalog: str, schema: str) -> QueryResult:
        cat = check_ident(catalog, "catalog")
        sql = (
            f"SELECT table_name, table_type, comment FROM {cat}.information_schema.tables "
            "WHERE table_schema = :schema ORDER BY table_name"
        )
        return await self.execute(sql, {"schema": schema.lower()}, max_rows=1000)

    async def describe_table(self, catalog: str, schema: str, table: str) -> QueryResult:
        cat = check_ident(catalog, "catalog")
        sql = (
            f"SELECT column_name, data_type, is_nullable, comment FROM {cat}.information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table ORDER BY ordinal_position"
        )
        return await self.execute(sql, {"schema": schema.lower(), "table": table.lower()}, max_rows=1000)


snowflake = Snowflake()
databricks = Databricks()
WAREHOUSES = {"snowflake": snowflake, "databricks": databricks}
