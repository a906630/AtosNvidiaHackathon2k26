from fastapi import APIRouter, HTTPException, Query

from app.schemas import (
    IncidentInput,
    IncidentResponse,
    IncidentResult,
    IncidentListItem,
    RealtimeLoad,
)
from app.store import (
    create_incident,
    get_incident,
    get_result,
    list_incidents,
    get_live_metrics,
)

router = APIRouter(prefix="/api/v1", tags=["Incidents"])


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
            raise HTTPException(status_code=404, detail="Incident not found.")
        raise HTTPException(
            status_code=202,
            detail="Incident is still processing. Follow /viz/stream/{incident_id}",
        )
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
