"""
Main LangGraph workflow for crisis management.

Flow:
  START -> supervisor -> specialized domain verifier
       -> cross_domain_correlator -> priority_assessor -> comms_generator -> END
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Literal

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from app.agents.cuda_utils import get_reranker
from app.agents.state import IncidentState
from app.agents.tools import get_search_tool
from app.config import get_settings
from app.data.public_sources import build_queries, now_date, social_tags, source_digest, source_urls
from app.store import get_live_metrics

logger = logging.getLogger(__name__)

DOMAIN_TO_NODE = {
    "flood": "flood_verifier",
    "cyber": "cyber_verifier",
    "terror": "terror_verifier",
    "infrastructure": "infrastructure_verifier",
    "traffic": "traffic_verifier",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _municipality(location: dict) -> str:
    """Return municipality name with backward compatibility for legacy payloads."""
    return location.get("municipality") or location.get("gmina", "")


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    if "```" in text:
        for part in text.split("```"):
            candidate = part.lstrip("json").strip()
            try:
                return json.loads(candidate)
            except Exception:
                continue
    return json.loads(text)


def _get_llm():
    settings = get_settings()
    from langchain_nvidia_ai_endpoints import ChatNVIDIA

    return ChatNVIDIA(
        model=settings.nvidia_model,
        base_url=settings.nvidia_base_url,
        api_key=settings.nvidia_api_key,
        temperature=0.1,
        max_tokens=2048,
    )


def _normalize_category(raw: str | None) -> str:
    if not raw:
        return "unknown"
    value = raw.strip().lower()
    aliases = {
        "flood": "flood",
        "powodz": "flood",
        "powódz": "flood",
        "cyber": "cyber",
        "cyberattack": "cyber",
        "terror": "terror",
        "terrorism": "terror",
        "infrastructure": "infrastructure",
        "infra": "infrastructure",
        "traffic": "traffic",
        "road": "traffic",
        "services": "services",
    }
    allowed = {"flood", "cyber", "terror", "infrastructure", "traffic", "services"}
    normalized = aliases.get(value, value)
    return normalized if normalized in allowed else "unknown"


def make_supervisor_node(llm):
    async def supervisor_node(state: IncidentState) -> dict:
        incident = state["incident_data"]
        location = incident.get("location", {})

        prompt = f"""You are the central router for Polish crisis management.
Classify the incident into one primary domain and suggest related domains.

Incident location: {_municipality(location) or '?'}, voivodeship {location.get('voivodeship', '?')}
Category hint: {incident.get('category_hint', 'unknown')}
Description: {incident.get('description', '')}
Source: {incident.get('source', {}).get('type', '?')} / {incident.get('source', {}).get('channel', '?')}
Timestamp: {incident.get('timestamp', '?')}

Allowed categories: flood, cyber, terror, infrastructure, traffic, services, unknown

Return JSON only:
{{
  "category": "one allowed category",
  "related_categories": ["zero or more allowed categories"],
  "classification_reasoning": "short reasoning"
}}"""

        try:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            result = _parse_json(response.content)
        except Exception as exc:
            logger.warning(f"Supervisor LLM error: {exc}")
            result = {
                "category": incident.get("category_hint", "unknown"),
                "related_categories": [],
                "classification_reasoning": f"Fallback classification due to LLM failure: {exc}",
            }

        category = _normalize_category(result.get("category"))
        related = [_normalize_category(item) for item in result.get("related_categories", [])]
        related = [item for item in related if item not in {"unknown", category}]

        return {
            "category": category,
            "related_categories": sorted(set(related)),
            "processing_log": [
                {
                    "agent": "supervisor",
                    "status": "completed",
                    "timestamp": _now(),
                    "details": {
                        "category": category,
                        "related_categories": sorted(set(related)),
                        "classification_reasoning": result.get("classification_reasoning", ""),
                    },
                }
            ],
        }

    return supervisor_node


def make_domain_verifier_node(llm, search_tool, domain: str):
    async def domain_verifier_node(state: IncidentState) -> dict:
        incident = state["incident_data"]
        location = incident.get("location", {})
        location_str = f"{_municipality(location)}, {location.get('voivodeship', '')}".strip(", ")
        description = incident.get("description", "")
        date_str = str(incident.get("timestamp", "") or now_date())[:10]

        queries = build_queries(domain, location_str, date_str, description)
        queries += [f"site:x.com {tag} {location_str}" for tag in social_tags(domain)[:3]]

        raw_results: list[str] = []
        if search_tool:
            for query in queries[:8]:
                try:
                    raw = await search_tool.ainvoke(query)
                    if isinstance(raw, list):
                        for item in raw[:2]:
                            raw_results.append(str(item.get("content", ""))[:700] if isinstance(item, dict) else str(item)[:700])
                    else:
                        raw_results.append(str(raw)[:700])
                except Exception as exc:
                    raw_results.append(f"[search-error: {exc}]")
        else:
            raw_results.append("[search-tool-unavailable]")

        valid_results = [item for item in raw_results if not item.startswith("[search-error") and item.strip()]
        reranker = get_reranker()
        top_results = reranker.rerank(
            query=f"{domain} incident in {location_str}. {description}",
            results=valid_results if valid_results else raw_results,
            top_k=4,
        )

        numbered = "\n".join(f"[{index + 1}] {snippet}" for index, snippet in enumerate(top_results))

        prompt = f"""You are a {domain} verification agent for Poland crisis operations.
Use the curated public source catalog and open-web findings to assess credibility.

Domain: {domain}
Location: {location_str}
Date: {date_str}
Description: {description}
Curated sources: {source_digest(domain)}
Suggested X tags: {social_tags(domain)}

Search snippets:
{numbered}

Return JSON only:
{{
  "credibility_score": 0.0,
  "deepfake_risk": 0.0,
  "reasoning": "short rationale",
  "sources_found": ["url or source name"],
  "key_findings": ["finding"],
  "corroborating_evidence": true,
  "related_categories": ["flood|cyber|terror|infrastructure|traffic|services"],
  "confidence": "high|medium|low"
}}"""

        try:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            result = _parse_json(response.content)
        except Exception as exc:
            logger.warning(f"{domain} verifier LLM error: {exc}")
            result = {
                "credibility_score": 0.5,
                "deepfake_risk": 0.3,
                "reasoning": f"Fallback due to LLM failure: {exc}",
                "sources_found": source_urls(domain)[:2],
                "key_findings": ["Automatic verification degraded"],
                "corroborating_evidence": False,
                "related_categories": [],
                "confidence": "low",
            }

        related = [_normalize_category(item) for item in result.get("related_categories", [])]
        related = [item for item in related if item not in {"unknown", domain}]

        return {
            "credibility_result": {
                "credibility_score": float(result.get("credibility_score", 0.5)),
                "deepfake_risk": float(result.get("deepfake_risk", 0.3)),
                "reasoning": result.get("reasoning", ""),
                "sources_found": result.get("sources_found", []),
                "key_findings": result.get("key_findings", []),
                "corroborating_evidence": bool(result.get("corroborating_evidence", False)),
            },
            "related_categories": sorted(set((state.get("related_categories", []) or []) + related)),
            "processing_log": [
                {
                    "agent": f"{domain}_verifier",
                    "status": "completed",
                    "timestamp": _now(),
                    "details": {
                        "domain": domain,
                        "queries": queries[:8],
                        "curated_sources": source_urls(domain),
                        "social_tags": social_tags(domain),
                        "results_fetched": len(raw_results),
                        "results_after_reranking": len(top_results),
                        "reranking_device": reranker.device,
                        "related_categories": related,
                        "confidence": result.get("confidence", "medium"),
                    },
                }
            ],
        }

    return domain_verifier_node


def make_cross_domain_correlator_node(llm):
    async def cross_domain_correlator_node(state: IncidentState) -> dict:
        category = state.get("category", "unknown")
        related = state.get("related_categories", []) or []
        credibility = state.get("credibility_result") or {}

        default_relations = {
            "flood": ["infrastructure", "traffic", "services"],
            "cyber": ["infrastructure", "services", "traffic"],
            "terror": ["traffic", "infrastructure", "services"],
            "infrastructure": ["traffic", "services", "cyber"],
            "traffic": ["infrastructure", "services"],
        }
        inferred = default_relations.get(category, [])

        prompt = f"""You are a cross-domain dependency agent.
Given primary category and preliminary related categories, infer systemic impact links.

Primary category: {category}
Current related categories: {related}
Credibility score: {credibility.get('credibility_score', 0.5)}
Key findings: {credibility.get('key_findings', [])}

Return JSON only:
{{
  "related_categories": ["flood|cyber|terror|infrastructure|traffic|services"],
  "dependency_graph": [
    {{"from": "cyber", "to": "infrastructure", "impact": "high|medium|low", "reason": "..."}}
  ],
  "operational_note": "short note"
}}"""

        try:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            result = _parse_json(response.content)
        except Exception as exc:
            logger.warning(f"Correlator LLM error: {exc}")
            result = {
                "related_categories": inferred,
                "dependency_graph": [
                    {
                        "from": category,
                        "to": target,
                        "impact": "medium",
                        "reason": "Default dependency fallback",
                    }
                    for target in inferred
                ],
                "operational_note": "Fallback dependency map",
            }

        llm_related = [_normalize_category(item) for item in result.get("related_categories", [])]
        merged_related = sorted(set([item for item in related + inferred + llm_related if item not in {"unknown", category}]))

        realtime_load = get_live_metrics(window_minutes=15)

        return {
            "related_categories": merged_related,
            "cross_domain_relations": {
                "dependency_graph": result.get("dependency_graph", []),
                "operational_note": result.get("operational_note", ""),
            },
            "realtime_load": realtime_load,
            "processing_log": [
                {
                    "agent": "cross_domain_correlator",
                    "status": "completed",
                    "timestamp": _now(),
                    "details": {
                        "primary_category": category,
                        "related_categories": merged_related,
                        "dependency_graph_size": len(result.get("dependency_graph", [])),
                        "incidents_in_window": realtime_load.get("incidents_in_window", 0),
                        "category_counts": realtime_load.get("category_counts", {}),
                    },
                }
            ],
        }

    return cross_domain_correlator_node


def make_priority_assessor_node(llm):
    async def priority_assessor_node(state: IncidentState) -> dict:
        incident = state["incident_data"]
        credibility = state.get("credibility_result") or {}
        category = state.get("category", "unknown")
        related = state.get("related_categories", []) or []
        realtime_load = state.get("realtime_load", {})
        location = incident.get("location", {})

        prompt = f"""You are a crisis prioritization officer.
Assign priority using direct impact, cross-domain dependency and real-time load.

Category: {category}
Related categories: {related}
Location: {_municipality(location) or '?'}, {location.get('voivodeship', '?')}
Description: {incident.get('description', '')}
Credibility: {credibility.get('credibility_score', 0.5):.0%}
Deepfake risk: {credibility.get('deepfake_risk', 0.3):.0%}
Realtime incidents in 15m window: {realtime_load.get('incidents_in_window', 0)}
Category load distribution: {realtime_load.get('category_counts', {})}

Priority scale:
P1_CRITICAL, P2_HIGH, P3_MEDIUM, P4_LOW

Return JSON only:
{{
  "priority": "P1_CRITICAL | P2_HIGH | P3_MEDIUM | P4_LOW",
  "reasoning": "short rationale",
  "recommended_actions": ["action 1", "action 2", "action 3"]
}}"""

        try:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            result = _parse_json(response.content)
        except Exception as exc:
            logger.warning(f"Priority assessor LLM error: {exc}")
            result = {
                "priority": "P2_HIGH",
                "reasoning": f"Fallback due to LLM failure: {exc}",
                "recommended_actions": ["Dispatch local services", "Run manual verification", "Issue preliminary alert"],
            }

        return {
            "priority": result.get("priority", "P2_HIGH"),
            "recommended_actions": result.get("recommended_actions", []),
            "processing_log": [
                {
                    "agent": "priority_assessor",
                    "status": "completed",
                    "timestamp": _now(),
                    "details": {
                        "priority": result.get("priority", "P2_HIGH"),
                        "reasoning": result.get("reasoning", ""),
                    },
                }
            ],
        }

    return priority_assessor_node


def make_comms_generator_node(llm):
    async def comms_generator_node(state: IncidentState) -> dict:
        incident = state["incident_data"]
        credibility = state.get("credibility_result") or {}
        priority = state.get("priority", "P2_HIGH")
        related = state.get("related_categories", []) or []
        actions = state.get("recommended_actions", [])
        realtime_load = state.get("realtime_load", {})
        location = incident.get("location", {})
        location_str = f"{_municipality(location) or 'area'}, {location.get('voivodeship', '')}".strip(", ")

        prompt = f"""You are a public crisis communication specialist.
Generate two messages: operations message and citizen message.

Category: {state.get('category', 'unknown')}
Related categories: {related}
Location: {location_str}
Priority: {priority}
Description: {incident.get('description', '')}
Credibility: {credibility.get('credibility_score', 0.5):.0%}
Actions: {actions}
Realtime load (15m): {realtime_load.get('incidents_in_window', 0)}

Return JSON only:
{{
  "service_message": "technical operational message",
  "citizen_message": "clear 2-3 sentence public message",
  "human_review_required": true,
  "review_reason": "reason or null"
}}"""

        try:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            result = _parse_json(response.content)
        except Exception as exc:
            logger.warning(f"Comms generator LLM error: {exc}")
            credibility_score = credibility.get("credibility_score", 0.5)
            result = {
                "service_message": (
                    f"ALERT {priority} | {location_str} | "
                    f"Category: {state.get('category', 'unknown')} | Related: {related} | "
                    f"Credibility: {credibility_score:.0%} | Actions: {', '.join(actions)}"
                ),
                "citizen_message": (
                    f"Attention residents in {location_str}. Services are actively responding. "
                    "Follow official updates and instructions from emergency authorities."
                ),
                "human_review_required": True,
                "review_reason": f"Automatic generation fallback due to error: {exc}",
            }

        human_review_required = result.get("human_review_required", False)
        review_reason = result.get("review_reason")
        if credibility.get("credibility_score", 1.0) < 0.4:
            human_review_required = True
            review_reason = review_reason or "Low credibility score (<40%)"

        return {
            "service_message": result.get("service_message", ""),
            "citizen_message": result.get("citizen_message", ""),
            "human_review_required": human_review_required,
            "processing_log": [
                {
                    "agent": "comms_generator",
                    "status": "completed",
                    "timestamp": _now(),
                    "details": {
                        "human_review_required": human_review_required,
                        "review_reason": review_reason,
                    },
                }
            ],
        }

    return comms_generator_node


def build_crisis_graph():
    llm = _get_llm()
    search_tool = get_search_tool()

    workflow = StateGraph(IncidentState)

    workflow.add_node("supervisor", make_supervisor_node(llm))
    workflow.add_node("flood_verifier", make_domain_verifier_node(llm, search_tool, "flood"))
    workflow.add_node("cyber_verifier", make_domain_verifier_node(llm, search_tool, "cyber"))
    workflow.add_node("terror_verifier", make_domain_verifier_node(llm, search_tool, "terror"))
    workflow.add_node("infrastructure_verifier", make_domain_verifier_node(llm, search_tool, "infrastructure"))
    workflow.add_node("traffic_verifier", make_domain_verifier_node(llm, search_tool, "traffic"))
    workflow.add_node("cross_domain_correlator", make_cross_domain_correlator_node(llm))
    workflow.add_node("priority_assessor", make_priority_assessor_node(llm))
    workflow.add_node("comms_generator", make_comms_generator_node(llm))

    workflow.add_edge(START, "supervisor")

    def route_after_supervisor(
        state: IncidentState,
    ) -> Literal[
        "flood_verifier",
        "cyber_verifier",
        "terror_verifier",
        "infrastructure_verifier",
        "traffic_verifier",
        "cross_domain_correlator",
    ]:
        category = _normalize_category(state.get("category", "unknown"))
        return DOMAIN_TO_NODE.get(category, "cross_domain_correlator")

    workflow.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {
            "flood_verifier": "flood_verifier",
            "cyber_verifier": "cyber_verifier",
            "terror_verifier": "terror_verifier",
            "infrastructure_verifier": "infrastructure_verifier",
            "traffic_verifier": "traffic_verifier",
            "cross_domain_correlator": "cross_domain_correlator",
        },
    )

    workflow.add_edge("flood_verifier", "cross_domain_correlator")
    workflow.add_edge("cyber_verifier", "cross_domain_correlator")
    workflow.add_edge("terror_verifier", "cross_domain_correlator")
    workflow.add_edge("infrastructure_verifier", "cross_domain_correlator")
    workflow.add_edge("traffic_verifier", "cross_domain_correlator")

    workflow.add_edge("cross_domain_correlator", "priority_assessor")
    workflow.add_edge("priority_assessor", "comms_generator")
    workflow.add_edge("comms_generator", END)

    return workflow.compile()


@lru_cache(maxsize=1)
def get_graph():
    logger.info("Building CZK LangGraph workflow...")
    graph = build_crisis_graph()
    logger.info("Graph ready.")
    return graph
