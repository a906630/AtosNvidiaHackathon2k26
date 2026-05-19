import logging

from fastapi import APIRouter, HTTPException, Query

from app.schemas import (
    IncidentInput,
    IncidentResponse,
    IncidentResult,
    IncidentListItem,
    RealtimeLoad,
    HumanApproval,
    Recommendation,
)
from app.store import (
    create_incident,
    get_incident,
    get_result,
    list_incidents,
    get_live_metrics,
    store_approval,
    get_approvals,
    get_recommendations,
)

router = APIRouter(prefix="/api/v1", tags=["Incidents"])
logger = logging.getLogger(__name__)


@router.post(
    "/incidents",
    response_model=IncidentResponse,
    status_code=202,
    summary="Submit incident",
    description="Accept an incident payload and start asynchronous multi-agent processing.",
    responses={
        202: {"description": "Incident accepted for processing."},
        422: {"description": "Validation error in request payload."},
    },
)
async def submit_incident(incident: IncidentInput):
    """Accept an incident and enqueue it for multi-agent processing."""
    incident_data = incident.model_dump(mode="json")
    incident_id = create_incident(incident_data)
    logger.info(
        "Incident accepted | id=%s | voivodeship=%s | source=%s",
        incident_id,
        (incident_data.get("location") or {}).get("voivodeship"),
        (incident_data.get("source") or {}).get("type"),
    )

    return IncidentResponse(
        incident_id=incident_id,
        status="accepted",
        stream_url=f"/viz/stream/{incident_id}",
        result_url=f"/api/v1/incidents/{incident_id}/result",
    )


@router.get(
    "/incidents/{incident_id}/result",
    response_model=IncidentResult,
    summary="Get final incident result",
    description="Return the final result when processing completes; returns 202 while still running.",
    responses={
        200: {"description": "Final multi-agent result returned."},
        202: {"description": "Incident is still being processed."},
        404: {"description": "Incident ID does not exist."},
    },
)
async def get_incident_result(incident_id: str):
    """Return final incident result when processing completes."""
    result = get_result(incident_id)
    if not result:
        incident = get_incident(incident_id)
        if not incident:
            logger.warning("Incident result requested but not found | id=%s", incident_id)
            raise HTTPException(status_code=404, detail="Incident not found.")
        logger.info("Incident still processing | id=%s", incident_id)
        raise HTTPException(
            status_code=202,
            detail="Incident is still processing. Follow /viz/stream/{incident_id}",
        )
    logger.info("Incident result returned | id=%s", incident_id)
    return result


@router.get(
    "/incidents",
    response_model=list[IncidentListItem],
    summary="List incidents",
    description="List all submitted incidents with optional final result when available.",
    responses={200: {"description": "Incident list returned."}},
)
async def list_all_incidents():
    return list_incidents()


@router.get(
    "/metrics/live",
    response_model=RealtimeLoad,
    summary="Get live load metrics",
    description="Return near-real-time incident volume, category counters, and minute-level ingestion rates.",
    responses={200: {"description": "Live metrics returned."}},
)
async def live_metrics(window_minutes: int = Query(default=15, ge=1, le=240)):
    return get_live_metrics(window_minutes=window_minutes)


@router.post(
    "/incidents/{incident_id}/approve",
    response_model=HumanApproval,
    status_code=201,
    summary="Submit human approval",
    description="Formal approval gate for critical actions (alerts, evacuations, etc).",
    responses={
        201: {"description": "Approval recorded."},
        404: {"description": "Incident not found."},
    },
)
async def approve_incident_action(
    incident_id: str,
    approval: HumanApproval,
):
    """Record formal human approval for an incident action."""
    incident = get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found.")

    approval_data = approval.model_dump(mode="json")
    store_approval(incident_id, approval_data)

    return approval


@router.get(
    "/incidents/{incident_id}/approvals",
    response_model=list[HumanApproval],
    summary="Get all approvals for an incident",
    description="Retrieve formal approval history for an incident.",
    responses={
        200: {"description": "Approval list returned."},
        404: {"description": "Incident not found."},
    },
)
async def get_incident_approvals(incident_id: str):
    """Return all recorded approvals for an incident."""
    incident = get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found.")

    return get_approvals(incident_id)


@router.get(
    "/incidents/{incident_id}/recommendations",
    response_model=list[Recommendation],
    summary="Get recommendations awaiting approval",
    description="Retrieve operational recommendations for an incident.",
    responses={
        200: {"description": "Recommendations list returned."},
        404: {"description": "Incident not found."},
    },
)
async def get_incident_recommendations(incident_id: str):
    """Return all recommendations for an incident."""
    incident = get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found.")

    return get_recommendations(incident_id)


