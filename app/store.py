"""
In-memory storage for incidents and results.
Replace with Redis/PostgreSQL in production.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

_incidents: dict[str, dict] = {}
_results: dict[str, dict] = {}
_approvals: dict[str, list[dict]] = {}
_recommendations: dict[str, list[dict]] = {}


def _parse_ts(ts: str | None) -> datetime:
    if not ts:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


def create_incident(incident_data: dict) -> str:
    incident_id = str(uuid.uuid4())
    _incidents[incident_id] = incident_data
    return incident_id


def get_incident(incident_id: str) -> Optional[dict]:
    return _incidents.get(incident_id)


def store_result(incident_id: str, result: dict) -> None:
    _results[incident_id] = result


def get_result(incident_id: str) -> Optional[dict]:
    return _results.get(incident_id)


def store_approval(incident_id: str, approval: dict) -> None:
    """Store a formal human approval for an incident action."""
    if incident_id not in _approvals:
        _approvals[incident_id] = []
    _approvals[incident_id].append(approval)


def get_approvals(incident_id: str) -> list[dict]:
    """Retrieve all approvals for an incident."""
    return _approvals.get(incident_id, [])


def store_recommendation(incident_id: str, recommendation: dict) -> None:
    """Store a recommendation awaiting approval."""
    if incident_id not in _recommendations:
        _recommendations[incident_id] = []
    _recommendations[incident_id].append(recommendation)


def get_recommendations(incident_id: str) -> list[dict]:
    """Retrieve all recommendations for an incident."""
    return _recommendations.get(incident_id, [])


def list_incidents() -> list[dict]:
    return [
        {"incident_id": iid, "result": _results.get(iid), **data}
        for iid, data in _incidents.items()
    ]


def get_recent_incidents(limit: int = 25) -> list[dict]:
    """Return a snapshot of the most recently added incidents."""
    safe_limit = max(1, int(limit))
    recent_items = list(_incidents.items())[-safe_limit:]
    return [
        {"incident_id": incident_id, **incident_data}
        for incident_id, incident_data in recent_items
    ]


def get_live_metrics(window_minutes: int = 15) -> dict:
    """Return near-real-time incident volume and category counters."""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=window_minutes)

    category_counts: Counter[str] = Counter()
    by_minute: Counter[str] = Counter()
    recent = 0

    for incident_id, incident in _incidents.items():
        result = _results.get(incident_id) or {}
        category = str(incident.get("category_hint") or result.get("category") or "unknown")
        category_counts[category] += 1

        ts = _parse_ts(incident.get("timestamp"))
        minute_key = ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M")
        by_minute[minute_key] += 1

        if ts >= window_start:
            recent += 1

    active_processing = sum(1 for iid in _incidents if iid not in _results)
    completed = len(_results)

    return {
        "total_incidents": len(_incidents),
        "active_processing": active_processing,
        "completed": completed,
        "recent_window_minutes": window_minutes,
        "incidents_in_window": recent,
        "category_counts": dict(category_counts),
        "ingestion_rate_by_minute": dict(sorted(by_minute.items())),
        "generated_at": now.isoformat(),
    }
