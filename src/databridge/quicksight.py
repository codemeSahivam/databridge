"""QuickSight: read anything, edit only dashboards the company has marked as editable.

Write operations are two-step: call without confirm=True to get a preview of the
change, show it to the user, then call again with confirm=True. Every write is
appended to the audit log.
"""

from __future__ import annotations

import asyncio
import json
import time
from functools import lru_cache
from typing import Any

from .config import settings


@lru_cache(maxsize=1)
def client():  # pragma: no cover - needs AWS credentials
    import boto3

    s = settings()
    session = boto3.Session(profile_name=s.aws_profile) if s.aws_profile else boto3.Session()
    return session.client("quicksight", region_name=s.aws_region)


def _account() -> str:
    acct = settings().aws_account_id
    if not acct:
        raise RuntimeError("QuickSight is not configured: set AWS_ACCOUNT_ID (and QUICKSIGHT_REGION).")
    return acct


async def call(method: str, **kwargs: Any) -> dict[str, Any]:
    fn = getattr(client(), method)
    resp = await asyncio.to_thread(fn, AwsAccountId=_account(), **kwargs)
    resp.pop("ResponseMetadata", None)
    return resp


def is_editable(dashboard_id: str) -> bool:
    s = settings()
    return dashboard_id in s.qs_editable_ids or any(dashboard_id.startswith(p) for p in s.qs_editable_prefixes)


def editable_rule() -> str:
    s = settings()
    return f"ids starting with {s.qs_editable_prefixes} or listed in QS_EDITABLE_DASHBOARD_IDS"


def audit(action: str, **details: Any) -> None:
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "action": action, **details}
    with open(settings().audit_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def summarize_definition(definition: dict[str, Any]) -> dict[str, Any]:
    """Compact view of a dashboard definition: sheets, visuals and the datasets used."""
    sheets = []
    for sh in definition.get("Sheets", []):
        visuals = []
        for v in sh.get("Visuals", []):
            if not v:
                continue
            vtype, body = next(iter(v.items()))  # each visual is {"BarChartVisual": {...}}
            title = (
                body.get("Title", {}).get("FormatText", {}).get("PlainText")
                or body.get("Title", {}).get("FormatText", {}).get("RichText")
                or ""
            )
            visuals.append({"type": vtype, "id": body.get("VisualId"), "title": title})
        sheets.append({"sheet_id": sh.get("SheetId"), "name": sh.get("Name"), "visuals": visuals})
    datasets = [d.get("Identifier") for d in definition.get("DataSetIdentifierDeclarations", [])]
    return {"sheets": sheets, "dataset_identifiers": datasets, "visual_count": sum(len(s["visuals"]) for s in sheets)}


def diff_summaries(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    def visuals(summary):
        return {(s["name"], v["id"]): f'{v["type"]}: {v["title"]}' for s in summary["sheets"] for v in s["visuals"]}

    o, n = visuals(old), visuals(new)
    return {
        "added_visuals": [f"[{k[0]}] {n[k]}" for k in n.keys() - o.keys()],
        "removed_visuals": [f"[{k[0]}] {o[k]}" for k in o.keys() - n.keys()],
        "changed_visuals": [f"[{k[0]}] {o[k]} -> {n[k]}" for k in n.keys() & o.keys() if n[k] != o[k]],
        "sheets_before": [s["name"] for s in old["sheets"]],
        "sheets_after": [s["name"] for s in new["sheets"]],
        "datasets_before": old["dataset_identifiers"],
        "datasets_after": new["dataset_identifiers"],
    }


def version_from_arn(version_arn: str) -> int:
    return int(version_arn.rstrip("/").split("/")[-1])
