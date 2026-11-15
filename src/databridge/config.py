"""All settings come from environment variables (or a .env file next to the server).

Nothing here is secret by itself; secrets are read from env / key files at connect time.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

try:  # optional convenience
    from dotenv import load_dotenv

    # .env in the directory the server is launched from (the repo root for Claude Code), or COMPANY_DATA_ENV.
    load_dotenv(os.getenv("COMPANY_DATA_ENV", os.path.join(os.getcwd(), ".env")))
except ImportError:  # pragma: no cover
    pass


def _list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [x.strip() for x in raw.split(",") if x.strip()]


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # ---- guardrails -------------------------------------------------------
    max_rows: int = field(default_factory=lambda: _int("MAX_ROWS", 500))
    query_timeout_s: int = field(default_factory=lambda: _int("QUERY_TIMEOUT_SECONDS", 120))
    # fnmatch patterns on fully-qualified, lower-cased table names, e.g. "*.pii.*,*.hr.salaries"
    blocked_tables: list[str] = field(default_factory=lambda: [p.lower() for p in _list("BLOCKED_TABLE_PATTERNS")])
    audit_log_path: str = field(default_factory=lambda: os.getenv("AUDIT_LOG_PATH", "audit.log.jsonl"))
    max_response_chars: int = field(default_factory=lambda: _int("MAX_RESPONSE_CHARS", 40000))

    # ---- Snowflake ---------------------------------------------------------
    sf_account: str = field(default_factory=lambda: os.getenv("SNOWFLAKE_ACCOUNT", ""))
    sf_user: str = field(default_factory=lambda: os.getenv("SNOWFLAKE_USER", ""))
    sf_role: str = field(default_factory=lambda: os.getenv("SNOWFLAKE_ROLE", ""))
    sf_warehouse: str = field(default_factory=lambda: os.getenv("SNOWFLAKE_WAREHOUSE", ""))
    sf_database: str = field(default_factory=lambda: os.getenv("SNOWFLAKE_DATABASE", ""))
    sf_schema: str = field(default_factory=lambda: os.getenv("SNOWFLAKE_SCHEMA", ""))
    sf_private_key_file: str = field(default_factory=lambda: os.getenv("SNOWFLAKE_PRIVATE_KEY_FILE", ""))
    sf_private_key_passphrase: str = field(default_factory=lambda: os.getenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE", ""))
    sf_authenticator: str = field(default_factory=lambda: os.getenv("SNOWFLAKE_AUTHENTICATOR", ""))  # e.g. externalbrowser

    # ---- Databricks --------------------------------------------------------
    dbx_host: str = field(default_factory=lambda: os.getenv("DATABRICKS_HOST", "").replace("https://", "").rstrip("/"))
    dbx_http_path: str = field(default_factory=lambda: os.getenv("DATABRICKS_HTTP_PATH", ""))
    dbx_token: str = field(default_factory=lambda: os.getenv("DATABRICKS_TOKEN", ""))
    dbx_client_id: str = field(default_factory=lambda: os.getenv("DATABRICKS_CLIENT_ID", ""))
    dbx_client_secret: str = field(default_factory=lambda: os.getenv("DATABRICKS_CLIENT_SECRET", ""))
    dbx_catalog: str = field(default_factory=lambda: os.getenv("DATABRICKS_CATALOG", ""))

    # ---- QuickSight --------------------------------------------------------
    aws_account_id: str = field(default_factory=lambda: os.getenv("AWS_ACCOUNT_ID", ""))
    aws_region: str = field(default_factory=lambda: os.getenv("QUICKSIGHT_REGION", os.getenv("AWS_REGION", "us-east-1")))
    aws_profile: str = field(default_factory=lambda: os.getenv("AWS_PROFILE", ""))
    # Only dashboards whose id starts with one of these prefixes, or is listed below, may be edited.
    qs_editable_prefixes: list[str] = field(default_factory=lambda: _list("QS_EDITABLE_PREFIXES") or ["claude-"])
    qs_editable_ids: list[str] = field(default_factory=lambda: _list("QS_EDITABLE_DASHBOARD_IDS"))
    # Principal (user/group ARN) that gets owner permissions on dashboards Claude creates.
    qs_owner_arn: str = field(default_factory=lambda: os.getenv("QS_OWNER_ARN", ""))


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()
