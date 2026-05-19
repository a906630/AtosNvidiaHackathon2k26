"""
Visualization endpoints:
  GET /viz/stream/{incident_id}  - SSE stream of agent execution
  GET /viz/graph                 - Mermaid topology generated from LangGraph
  GET /viz/graph/json            - JSON topology for external consumers
  GET /viz/output/{incident_id}  - JSON output preview for one incident
  GET /                          - Dashboard HTML
"""
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from app.agents.graph import get_graph
from app.schemas import GraphJsonResponse, GraphRunPreviewResponse, MermaidGraphResponse
from app.store import get_incident, get_live_metrics, get_recent_incidents, get_result, store_result

router = APIRouter(tags=["Visualization"])
logger = logging.getLogger(__name__)


def _safe_serialize(obj) -> str:
    """Serialize an object to JSON with a safe fallback."""
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        return json.dumps({"error": "serialization_failed"})


@router.get(
    "/viz/stream/{incident_id}",
    summary="Stream incident processing",
    description="Server-Sent Events stream with node-by-node updates and final aggregated result.",
    responses={
        200: {"description": "SSE stream started."},
        404: {"description": "Incident ID does not exist."},
    },
)
async def stream_incident(incident_id: str):
    """Stream node-level updates while the graph is running."""
    incident_data = get_incident(incident_id)
    if not incident_data:
        raise HTTPException(status_code=404, detail="Incident does not exist.")
    logger.info("SSE stream started | incident_id=%s", incident_id)

    async def generate():
        graph = get_graph()

        initial_state = {
            "incident_data": incident_data,
            "category": "unknown",
            "related_categories": [],
            "selected_domains": [],
            "recent_incidents": get_recent_incidents(limit=25),
            "credibility_result": None,
            "domain_verifications": {},
            "cross_domain_relations": {},
            "realtime_load": get_live_metrics(window_minutes=15),
            "priority": None,
            "recommended_actions": [],
            "service_message": None,
            "citizen_message": None,
            "human_review_required": False,
            "processing_log": [],
            "error": None,
        }

        node_descriptions = {
            "supervisor": "Route incident to a primary specialized agent",
            "flood_verifier": "Verify flood signals using open web/public data",
            "cyber_verifier": "Verify cyber attack indicators and advisories",
            "terror_verifier": "Verify potential terror threat signals",
            "infrastructure_verifier": "Verify urban infrastructure outage reports",
            "traffic_verifier": "Verify road congestion/incidents from public sources",
            "cross_domain_correlator": "Infer cross-domain dependencies",
            "priority_assessor": "Assign priority and operational actions",
            "comms_generator": "Generate messages for services and citizens",
        }

        final_state = initial_state.copy()

        try:
            async for chunk in graph.astream(initial_state, stream_mode="updates"):
                for node_name, state_delta in chunk.items():
                    if node_name == "__end__":
                        continue

                    for key, val in state_delta.items():
                        if key == "processing_log":
                            final_state["processing_log"] = final_state.get("processing_log", []) + val
                        else:
                            final_state[key] = val

                    event = {
                        "type": "node_complete",
                        "node": node_name,
                        "description": node_descriptions.get(node_name, node_name),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "data": state_delta,
                    }
                    yield f"data: {_safe_serialize(event)}\n\n"

            result = {
                "incident_id": incident_id,
                "category": final_state.get("category", "unknown"),
                "related_categories": final_state.get("related_categories", []),
                "credibility": final_state.get("credibility_result"),
                "priority": final_state.get("priority", "P2_HIGH"),
                "recommended_actions": final_state.get("recommended_actions", []),
                "service_message": final_state.get("service_message", ""),
                "citizen_message": final_state.get("citizen_message", ""),
                "human_review_required": final_state.get("human_review_required", False),
                "realtime_load": final_state.get("realtime_load", get_live_metrics(window_minutes=15)),
                "processing_log": final_state.get("processing_log", []),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
            store_result(incident_id, result)
            logger.info("SSE stream completed | incident_id=%s", incident_id)
            yield f"data: {_safe_serialize({'type': 'done', 'incident_id': incident_id, 'result': result})}\n\n"

        except Exception as exc:
            logger.exception(f"Processing error for {incident_id}: {exc}")
            yield f"data: {_safe_serialize({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get(
    "/viz/graph",
    response_model=MermaidGraphResponse,
    summary="Get graph topology",
    description="Return Mermaid diagram generated from current LangGraph workflow.",
    responses={200: {"description": "Mermaid graph returned."}},
)
async def get_graph_diagram():
    try:
        graph = get_graph()
        mermaid_str = graph.get_graph().draw_mermaid()
        return {"mermaid": mermaid_str}
    except Exception:
        return {
            "mermaid": """graph TD
    START([Start]) --> SUP
    SUP[Supervisor] --> FLOOD[Flood Agent]
    SUP --> CYBER[Cyber Agent]
    SUP --> TERROR[Terror Agent]
    SUP --> INFRA[Infrastructure Agent]
    SUP --> TRAF[Traffic Agent]
    FLOOD --> CORR[Cross-domain Correlator]
    CYBER --> CORR
    TERROR --> CORR
    INFRA --> CORR
    TRAF --> CORR
    CORR --> PRIO[Priority Assessor]
    PRIO --> COMMS[Comms Generator]
    COMMS --> DONE([Done])"""
        }


@router.get(
    "/viz/graph/json",
    response_model=GraphJsonResponse,
    summary="Get graph topology as JSON",
    description="Return workflow topology as structured JSON nodes and edges.",
    responses={200: {"description": "Graph JSON topology returned."}},
)
async def get_graph_json():
    nodes = [
        "supervisor",
        "flood_verifier",
        "cyber_verifier",
        "terror_verifier",
        "infrastructure_verifier",
        "traffic_verifier",
        "cross_domain_correlator",
        "priority_assessor",
        "comms_generator",
    ]
    edges = [
        {"from": "start", "to": "supervisor"},
        {"from": "supervisor", "to": "flood_verifier"},
        {"from": "supervisor", "to": "cyber_verifier"},
        {"from": "supervisor", "to": "terror_verifier"},
        {"from": "supervisor", "to": "infrastructure_verifier"},
        {"from": "supervisor", "to": "traffic_verifier"},
        {"from": "flood_verifier", "to": "cross_domain_correlator"},
        {"from": "cyber_verifier", "to": "cross_domain_correlator"},
        {"from": "terror_verifier", "to": "cross_domain_correlator"},
        {"from": "infrastructure_verifier", "to": "cross_domain_correlator"},
        {"from": "traffic_verifier", "to": "cross_domain_correlator"},
        {"from": "cross_domain_correlator", "to": "priority_assessor"},
        {"from": "priority_assessor", "to": "comms_generator"},
        {"from": "comms_generator", "to": "end"},
    ]
    return {"nodes": nodes, "edges": edges}


@router.get(
    "/viz/output/{incident_id}",
    response_model=GraphRunPreviewResponse,
    summary="Get incident output preview as JSON",
    description="Return final output payload in JSON form from visualization scope.",
    responses={
        200: {"description": "Final output is available."},
        202: {"description": "Incident is still being processed."},
        404: {"description": "Incident ID does not exist."},
    },
)
async def get_incident_output_preview(incident_id: str):
    incident = get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident does not exist.")

    result = get_result(incident_id)
    if not result:
        raise HTTPException(status_code=202, detail="Incident is still processing.")

    return {
        "incident_id": incident_id,
        "status": "completed",
        "result": result,
        "message": "Output payload is available.",
    }


@router.get(
    "/",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def dashboard():
    try:
        with open("static/dashboard.html", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("<h1>Dashboard unavailable - missing static/dashboard.html</h1>", status_code=500)
