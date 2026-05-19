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

import httpx

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from app.agents.cuda_utils import get_reranker
from app.agents.state import IncidentState
from app.agents.tools import get_search_tool
from app.config import get_settings
from app.data.public_sources import build_queries, now_date, social_tags, source_digest, source_urls
from app.security.prompt_guard import guard_prompt
from app.store import get_live_metrics, get_recent_incidents

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


def _recent_incidents_context(incidents: list[dict], limit: int = 25) -> str:
    """Build a compact multi-incident context for correlation prompts."""
    recent = incidents[-limit:]
    rows: list[str] = []
    for incident in recent:
        location = incident.get("location", {}) or {}
        rows.append(
            " - id={id} | category_hint={cat} | location={municipality}/{voivodeship} | ts={ts} | desc={desc}".format(
                id=incident.get("incident_id", "n/a"),
                cat=incident.get("category_hint", "unknown"),
                municipality=_municipality(location) or "?",
                voivodeship=location.get("voivodeship", "?"),
                ts=incident.get("timestamp", "?"),
                desc=str(incident.get("description", ""))[:180],
            )
        )
    return "\n".join(rows) if rows else " - no recent incidents available"


def _get_llm(model: str | None = None):
    settings = get_settings()
    from langchain_nvidia_ai_endpoints import ChatNVIDIA

    return ChatNVIDIA(
        model=model or settings.nvidia_model,
        base_url=settings.nvidia_base_url,
        api_key=settings.nvidia_api_key,
        temperature=0.1,
        max_tokens=2048,
    )


def _agent_model_map() -> dict[str, str]:
    settings = get_settings()
    fallback = settings.nvidia_model
    return {
        "supervisor": settings.nvidia_model_supervisor or fallback,
        "domain_verifier": settings.nvidia_model_domain_verifier or fallback,
        "cross_domain_correlator": settings.nvidia_model_cross_domain_correlator or fallback,
        "priority_assessor": settings.nvidia_model_priority_assessor or fallback,
        "comms_generator": settings.nvidia_model_comms_generator or fallback,
    }


def _fetch_nim_models() -> set[str]:
    """Fetch available model IDs from NVIDIA NIM; return empty set on failure."""
    settings = get_settings()
    models_url = f"{settings.nvidia_base_url.rstrip('/')}/models"
    headers = {}
    if settings.nvidia_api_key and settings.nvidia_api_key != "no-key":
        headers["Authorization"] = f"Bearer {settings.nvidia_api_key}"

    try:
        response = httpx.get(models_url, headers=headers, timeout=5.0)
        response.raise_for_status()
        payload = response.json()
        entries = payload.get("data", []) if isinstance(payload, dict) else []
        return {
            str(item.get("id", "")).strip()
            for item in entries
            if isinstance(item, dict) and item.get("id")
        }
    except Exception as exc:
        logger.warning(f"Unable to fetch NVIDIA NIM model catalog from {models_url}: {exc}")
        return set()


def _select_default_model(available: set[str], configured_default: str) -> str:
    """Pick a safe default model from available NIM catalog."""
    if configured_default in available:
        return configured_default
    # Deterministic choice for reproducibility in logs.
    return sorted(available)[0]


def _resolve_agent_model_map() -> dict[str, str]:
    """Validate mapped models against NIM catalog and fallback to default model when needed."""
    settings = get_settings()
    mapped = _agent_model_map()
    available = _fetch_nim_models()
    if not available:
        return mapped

    resolved = mapped.copy()
    fallback = _select_default_model(available, settings.nvidia_model)
    if fallback != settings.nvidia_model:
        logger.warning(
            "Configured NVIDIA_MODEL '%s' is not in NIM catalog. Using '%s' as effective fallback.",
            settings.nvidia_model,
            fallback,
        )
    for role, model in mapped.items():
        if model in available:
            continue
        logger.warning(
            "Model '%s' for role '%s' not found in NIM catalog. Falling back to '%s'.",
            model,
            role,
            fallback,
        )
        resolved[role] = fallback
    return resolved


def _fallback_model_candidates(current_model: str | None) -> list[str]:
    """Build retry candidates for failed model invocations."""
    settings = get_settings()
    candidates: list[str] = []
    available = _fetch_nim_models()

    if settings.nvidia_model and settings.nvidia_model != current_model:
        candidates.append(settings.nvidia_model)

    for model in sorted(available):
        if model != current_model and model not in candidates:
            candidates.append(model)

    return candidates


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
            response, guard_info = await _guarded_ainvoke(llm, prompt, "supervisor")
            result = _parse_json(response.content)
        except Exception as exc:
            logger.warning(f"Supervisor LLM error: {exc}")
            result = {
                "category": "unknown",
                "related_categories": [],
                "classification_reasoning": f"Fallback classification due to LLM failure: {exc}",
            }
            guard_info = {"blocked": False}

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
                        "guardrails": guard_info,
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
                logger.info(f"[{domain}_verifier] search query: {query}")
                try:
                    raw = await search_tool.ainvoke(query)
                    if isinstance(raw, list):
                        logger.info(f"[{domain}_verifier] search returned {len(raw)} items")
                        for item in raw[:2]:
                            raw_results.append(str(item.get("content", ""))[:700] if isinstance(item, dict) else str(item)[:700])
                    else:
                        logger.info(f"[{domain}_verifier] search returned non-list payload")
                        raw_results.append(str(raw)[:700])
                except Exception as exc:
                    logger.warning(f"[{domain}_verifier] search error for query='{query}': {exc}")
                    raw_results.append(f"[search-error: {exc}]")
        else:
            logger.warning(f"[{domain}_verifier] search-tool-unavailable")
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
            response, guard_info = await _guarded_ainvoke(llm, prompt, f"{domain}_verifier")
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
            guard_info = {"blocked": False}

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
                        "media_sources_checked": {
                            "curated_urls": source_urls(domain),
                            "x_hashtags_monitored": social_tags(domain),
                            "total_queries_executed": len(queries[:8]),
                        },
                        "queries": queries[:8],
                        "curated_sources": source_urls(domain),
                        "social_tags": social_tags(domain),
                        "results_fetched": len(raw_results),
                        "results_after_reranking": len(top_results),
                        "reranking_device": reranker.device,
                        "top_results_preview": top_results[:2] if len(top_results) >= 2 else top_results,
                        "related_categories": related,
                        "confidence": result.get("confidence", "medium"),
                        "guardrails": guard_info,
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
        recent_incidents = state.get("recent_incidents") or get_recent_incidents(limit=25)
        recent_context = _recent_incidents_context(recent_incidents, limit=25)

        default_relations = {
            "flood": ["infrastructure", "traffic", "services"],
            "cyber": ["infrastructure", "services", "traffic"],
            "terror": ["traffic", "infrastructure", "services"],
            "infrastructure": ["traffic", "services", "cyber"],
            "traffic": ["infrastructure", "services"],
        }
        inferred = default_relations.get(category, [])

        prompt = f"""You are a cross-domain dependency agent.
Given the current incident and the most recently added incidents, infer systemic impact links.

Primary category: {category}
Current related categories: {related}
Credibility score: {credibility.get('credibility_score', 0.5)}
Key findings: {credibility.get('key_findings', [])}

Recent incidents snapshot (analyze all records below, not only current one):
{recent_context}

Return JSON only:
{{
  "related_categories": ["flood|cyber|terror|infrastructure|traffic|services"],
  "dependency_graph": [
    {{"from": "cyber", "to": "infrastructure", "impact": "high|medium|low", "reason": "..."}}
  ],
  "operational_note": "short note"
}}"""

        try:
            response, guard_info = await _guarded_ainvoke(llm, prompt, "cross_domain_correlator")
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
            guard_info = {"blocked": False}

        llm_related = [_normalize_category(item) for item in result.get("related_categories", [])]
        merged_related = sorted(set([item for item in related + inferred + llm_related if item not in {"unknown", category}]))

        realtime_load = get_live_metrics(window_minutes=15)

        return {
            "related_categories": merged_related,
            "cross_domain_relations": {
                "dependency_graph": result.get("dependency_graph", []),
                "operational_note": result.get("operational_note", ""),
                "analyzed_recent_incidents": len(recent_incidents),
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
                        "analyzed_recent_incidents": len(recent_incidents),
                        "incidents_in_window": realtime_load.get("incidents_in_window", 0),
                        "category_counts": realtime_load.get("category_counts", {}),
                        "guardrails": guard_info,
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
        location_str = f"{_municipality(location) or 'area'}, {location.get('voivodeship', '')}".strip(", ")

        prompt = f"""You are a crisis prioritization officer.
Assign priority using direct impact, cross-domain dependency and real-time load.
All textual outputs MUST be in Polish.

Category: {category}
Related categories: {related}
Location: {location_str}
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
  "reasoning": "krotkie uzasadnienie po polsku",
  "recommended_actions": ["zalecenie 1 po polsku", "zalecenie 2 po polsku", "zalecenie 3 po polsku"]
}}"""

        try:
            response, guard_info = await _guarded_ainvoke(llm, prompt, "priority_assessor")
            result = _parse_json(response.content)
        except Exception as exc:
            logger.warning(f"Priority assessor LLM error: {exc}")
            result = {
                "priority": "P2_HIGH",
                "reasoning": f"Fallback z powodu bledu LLM: {exc}",
                "recommended_actions": [
                    "Skierowac lokalne sluzby do obszaru zdarzenia",
                    "Uruchomic reczna weryfikacje informacji",
                    "Wydac wstepny komunikat ostrzegawczy",
                ],
            }
            guard_info = {"blocked": False}

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
                        "guardrails": guard_info,
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
Both messages MUST be in Polish.

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
  "service_message": "techniczny komunikat operacyjny po polsku",
  "citizen_message": "jasny komunikat publiczny 2-3 zdania po polsku",
  "human_review_required": true,
  "review_reason": "powod po polsku lub null"
}}"""

        try:
            response, guard_info = await _guarded_ainvoke(llm, prompt, "comms_generator")
            result = _parse_json(response.content)
        except Exception as exc:
            logger.warning(f"Comms generator LLM error: {exc}")
            credibility_score = credibility.get("credibility_score", 0.5)
            result = {
                "service_message": (
                    f"ALERT {priority} | {location_str} | "
                    f"Kategoria: {state.get('category', 'unknown')} | Powiazane: {related} | "
                    f"Wiarygodnosc: {credibility_score:.0%} | Dzialania: {', '.join(actions)}"
                ),
                "citizen_message": (
                    f"Uwaga mieszkancy obszaru {location_str}. Sluzby aktywnie prowadza dzialania. "
                    "Prosze sledzic oficjalne komunikaty i stosowac sie do polecen sluzb ratunkowych."
                ),
                "human_review_required": True,
                "review_reason": f"Automatyczny fallback z powodu bledu: {exc}",
            }
            guard_info = {"blocked": False}

        human_review_required = result.get("human_review_required", False)
        review_reason = result.get("review_reason")
        if credibility.get("credibility_score", 1.0) < 0.4:
            human_review_required = True
            review_reason = review_reason or "Niska wiarygodnosc (<40%)"

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
                        "guardrails": guard_info,
                    },
                }
            ],
        }

    return comms_generator_node


async def _guarded_ainvoke(llm, prompt: str, context: str):
    """Run prompt guardrails before invoking the LLM."""
    sanitized_prompt, guard_info = guard_prompt(prompt, context=context)
    current_model = getattr(llm, "model", None)
    try:
        logger.info("LLM invoke start | context=%s | model=%s", context, current_model)
        response = await llm.ainvoke([HumanMessage(content=sanitized_prompt)])
        logger.info("LLM invoke ok    | context=%s | model=%s", context, current_model)
    except Exception as exc:
        is_not_found = "404" in str(exc) or "Not Found" in str(exc)
        if not is_not_found:
            logger.warning("LLM invoke error | context=%s | model=%s | error=%s", context, current_model, exc)
            raise

        retry_chain = _fallback_model_candidates(current_model)
        logger.warning(
            "LLM model_not_found | context=%s | model=%s | retry_candidates=%s",
            context,
            current_model,
            retry_chain,
        )

        last_exc = exc
        for candidate in retry_chain:
            try:
                retry_llm = _get_llm(candidate)
                logger.info("LLM retry start  | context=%s | model=%s", context, candidate)
                response = await retry_llm.ainvoke([HumanMessage(content=sanitized_prompt)])
                logger.info("LLM retry ok     | context=%s | model=%s", context, candidate)
                guard_info = {
                    **guard_info,
                    "llm_model_fallback": {
                        "from": current_model,
                        "to": candidate,
                        "reason": "model_not_found",
                    },
                }
                return response, guard_info
            except Exception as retry_exc:
                last_exc = retry_exc
                logger.warning("LLM retry failed | context=%s | model=%s | error=%s", context, candidate, retry_exc)

        raise last_exc
    return response, guard_info


def build_crisis_graph(model_map: dict[str, str] | None = None):
    model_map = model_map or _resolve_agent_model_map()
    llm_supervisor = _get_llm(model_map["supervisor"])
    llm_domain_verifier = _get_llm(model_map["domain_verifier"])
    llm_cross_domain = _get_llm(model_map["cross_domain_correlator"])
    llm_priority = _get_llm(model_map["priority_assessor"])
    llm_comms = _get_llm(model_map["comms_generator"])
    search_tool = get_search_tool()

    workflow = StateGraph(IncidentState)

    workflow.add_node("supervisor", make_supervisor_node(llm_supervisor))
    workflow.add_node("flood_verifier", make_domain_verifier_node(llm_domain_verifier, search_tool, "flood"))
    workflow.add_node("cyber_verifier", make_domain_verifier_node(llm_domain_verifier, search_tool, "cyber"))
    workflow.add_node("terror_verifier", make_domain_verifier_node(llm_domain_verifier, search_tool, "terror"))
    workflow.add_node("infrastructure_verifier", make_domain_verifier_node(llm_domain_verifier, search_tool, "infrastructure"))
    workflow.add_node("traffic_verifier", make_domain_verifier_node(llm_domain_verifier, search_tool, "traffic"))
    workflow.add_node("cross_domain_correlator", make_cross_domain_correlator_node(llm_cross_domain))
    workflow.add_node("priority_assessor", make_priority_assessor_node(llm_priority))
    workflow.add_node("comms_generator", make_comms_generator_node(llm_comms))

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
    available_models = sorted(_fetch_nim_models())
    if available_models:
        logger.info("NIM model catalog loaded | count=%s | models=%s", len(available_models), available_models)
    else:
        logger.warning("NIM model catalog unavailable during graph bootstrap.")
    resolved_map = _resolve_agent_model_map()
    logger.info(f"Per-agent model map: {resolved_map}")
    graph = build_crisis_graph(model_map=resolved_map)
    logger.info("Graph ready.")
    return graph
