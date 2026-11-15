"""Read-only SQL enforcement.

Every query Claude sends is parsed with sqlglot before it reaches a warehouse:
  * exactly one statement
  * must be a SELECT / WITH / UNION-style query (or DESCRIBE)
  * no DML / DDL / procedural commands anywhere in the tree
  * no table matching BLOCKED_TABLE_PATTERNS
  * a row LIMIT is always applied

This is defence in depth: the service accounts should ALSO be read-only in
Snowflake (role grants) and Databricks (Unity Catalog SELECT only).
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

DIALECTS = {"snowflake": "snowflake", "databricks": "databricks"}

# Node types that must never appear anywhere in a read-only query.
_FORBIDDEN = tuple(
    t
    for t in (
        getattr(exp, name, None)
        for name in (
            "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "AlterTable",
            "TruncateTable", "Command", "Grant", "Revoke", "Copy", "Use", "Set", "Transaction",
            "Commit", "Rollback", "Into", "LoadData", "Pragma", "Call", "Execute",
        )
    )
    if t is not None
)


class UnsafeQueryError(ValueError):
    """Raised with a message that tells Claude how to fix the query."""


@dataclass
class GuardedQuery:
    sql: str            # the SQL that will actually run (with LIMIT applied)
    tables: list[str]   # fully-qualified tables referenced


def _table_name(t: exp.Table) -> str:
    parts = [p for p in (t.catalog, t.db, t.name) if p]
    return ".".join(parts).lower()


def guard(sql: str, dialect: str, max_rows: int, blocked_patterns: list[str]) -> GuardedQuery:
    if dialect not in DIALECTS:
        raise UnsafeQueryError(f"Unknown dialect '{dialect}'. Use one of: {', '.join(DIALECTS)}.")
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        raise UnsafeQueryError("Empty query.")

    try:
        statements = [s for s in sqlglot.parse(sql, read=DIALECTS[dialect]) if s is not None]
    except sqlglot.errors.ParseError as e:
        raise UnsafeQueryError(f"Could not parse the SQL as {dialect}: {str(e).splitlines()[0]}") from e

    if len(statements) != 1:
        raise UnsafeQueryError("Send exactly one statement per call (no ';'-separated batches).")
    tree = statements[0]

    if isinstance(tree, exp.Describe):
        return GuardedQuery(sql=tree.sql(dialect=DIALECTS[dialect]), tables=[_table_name(t) for t in tree.find_all(exp.Table)])

    if not isinstance(tree, exp.Query):
        raise UnsafeQueryError(
            f"Only read queries are allowed (SELECT / WITH / UNION / DESCRIBE). Got: {type(tree).__name__}."
        )

    for node in tree.walk():
        if isinstance(node, _FORBIDDEN):
            raise UnsafeQueryError(f"Write or admin operation '{type(node).__name__}' is not allowed. This connector is read-only.")

    tables = sorted({_table_name(t) for t in tree.find_all(exp.Table) if t.name})
    # CTE names are not real tables; ignore them for blocking.
    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for name in tables:
        if name in cte_names:
            continue
        for pat in blocked_patterns:
            if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(name.split(".")[-1], pat):
                raise UnsafeQueryError(
                    f"Table '{name}' is blocked by company policy (pattern '{pat}'). Use an approved table instead."
                )

    # Always cap rows: wrap the query so user-written LIMITs above max_rows are also capped.
    limited = (
        exp.select("*")
        .from_(exp.Subquery(this=tree.copy(), alias=exp.TableAlias(this=exp.to_identifier("_q"))))
        .limit(max_rows + 1)  # +1 lets us tell Claude the result was truncated
    )
    return GuardedQuery(sql=limited.sql(dialect=DIALECTS[dialect]), tables=[t for t in tables if t not in cte_names])
