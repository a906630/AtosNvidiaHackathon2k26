"""
Main LangGraph workflow for crisis management.

Flow:
  START -> supervisor -> specialized domain verifier
       -> cross_domain_correlator -> priority_assessor -> comms_generator -> END
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import TypedDict

import httpx

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from app.agents.credibility_model import (
    AdvancedCredibilityModel,
    estimate_llm_credibility_bounds,
)
from app.agents.cuda_utils import get_reranker
from app.agents.state import IncidentState
from app.agents.tools import get_search_tool
from app.config import get_settings
from app.data.public_sources import build_queries, now_date, social_tags, source_digest, source_urls
from app.security.prompt_guard import guard_prompt
from app.store import get_live_metrics, get_recent_incidents

logger = logging.getLogger(__name__)


class MediaCacheEntry(TypedDict):
    fetched_at: datetime
    results: list[str]


_media_cache: dict[str, MediaCacheEntry] = {}
_media_cache_lock = asyncio.Lock()

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


def _as_str(value, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _as_list_str(value) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _extract_related_categories(raw_value) -> list[str]:
    """Normalize related categories from LLM output (supports pipe/comma separated tokens)."""
    items = _as_list_str(raw_value)
    out: list[str] = []
    for item in items:
        for token in item.replace(",", "|").split("|"):
            cleaned = token.strip()
            if cleaned:
                out.append(cleaned)
    return out


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
        temperature=0.0,
        max_tokens=settings.nvidia_max_tokens,
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


def _select_domains(primary_category: str, related_categories: list[str]) -> list[str]:
    """Select one or more domain verifiers to run after supervisor classification."""
    selected: list[str] = []
    for item in [primary_category, *(related_categories or [])]:
        normalized = _normalize_category(item)
        if normalized in DOMAIN_TO_NODE and normalized not in selected:
            selected.append(normalized)
    if not selected:
        # Safe fallback: run all domain verifiers when classification is uncertain.
        return list(DOMAIN_TO_NODE.keys())
    return selected


async def _search_public_sources_cached(
    *,
    domain: str,
    queries: list[str],
    search_tool,
    location_str: str,
) -> tuple[list[str], dict]:
    """Query public sources with in-memory TTL cache and periodic refresh."""
    settings = get_settings()
    cache_key = f"{domain}|{location_str.strip().lower()}"
    refresh_delta = timedelta(minutes=max(1, settings.media_refresh_minutes))
    now = datetime.now(timezone.utc)

    async with _media_cache_lock:
        cached = _media_cache.get(cache_key)
        if cached and (now - cached["fetched_at"]) < refresh_delta:
            return cached["results"], {
                "cache_hit": True,
                "cache_key": cache_key,
                "fetched_at": cached["fetched_at"].isoformat(),
                "age_seconds": int((now - cached["fetched_at"]).total_seconds()),
            }

    max_queries = max(1, settings.media_max_queries)
    per_query = max(1, settings.media_results_per_query)
    raw_results: list[str] = []

    if search_tool:
        for query in queries[:max_queries]:
            logger.info(f"[{domain}_verifier] search query: {query}")
            try:
                raw = await search_tool.ainvoke(query)
                if isinstance(raw, list):
                    logger.info(f"[{domain}_verifier] search returned {len(raw)} items")
                    for item in raw[:per_query]:
                        snippet = str(item.get("content", ""))[:700] if isinstance(item, dict) else str(item)[:700]
                        raw_results.append(snippet)
                else:
                    logger.info(f"[{domain}_verifier] search returned non-list payload")
                    raw_results.append(str(raw)[:700])
            except Exception as exc:
                logger.warning(f"[{domain}_verifier] search error for query='{query}': {exc}")
                raw_results.append(f"[search-error: {exc}]")
    else:
        logger.warning(f"[{domain}_verifier] search-tool-unavailable")
        raw_results.append("[search-tool-unavailable]")

    async with _media_cache_lock:
        _media_cache[cache_key] = {
            "fetched_at": now,
            "results": raw_results,
        }

    return raw_results, {
        "cache_hit": False,
        "cache_key": cache_key,
        "fetched_at": now.isoformat(),
        "age_seconds": 0,
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

        category = _normalize_category(_as_str(result.get("category"), "unknown"))
        related = [_normalize_category(item) for item in _as_list_str(result.get("related_categories"))]
        related = [item for item in related if item not in {"unknown", category}]
        selected_domains = _select_domains(category, related)

        return {
            "category": category,
            "related_categories": sorted(set(related)),
            "selected_domains": selected_domains,
            "processing_log": [
                {
                    "agent": "supervisor",
                    "status": "completed",
                    "timestamp": _now(),
                    "details": {
                        "category": category,
                        "related_categories": sorted(set(related)),
                        "selected_domains": selected_domains,
                        "classification_reasoning": result.get("classification_reasoning", ""),
                        "guardrails": guard_info,
                    },
                }
            ],
        }

    return supervisor_node


def make_domain_verifier_node(llm, search_tool, domain: str):
     async def domain_verifier_node(state: IncidentState) -> dict:
         selected_domains = state.get("selected_domains") or []
         if domain not in selected_domains:
             return {
                 "processing_log": [
                     {
                         "agent": f"{domain}_verifier",
                         "status": "skipped",
                         "timestamp": _now(),
                         "details": {"reason": "domain_not_selected", "selected_domains": selected_domains},
                     }
                 ]
             }

         incident = state["incident_data"]
         location = incident.get("location", {})
         location_str = f"{_municipality(location)}, {location.get('voivodeship', '')}".strip(", ")
         description = incident.get("description", "")
         date_str = str(incident.get("timestamp", "") or now_date())[:10]

         queries = build_queries(domain, location_str, date_str, description)
         queries += [f"site:x.com {tag} {location_str}" for tag in social_tags(domain)[:3]]

         raw_results, cache_meta = await _search_public_sources_cached(
             domain=domain,
             queries=queries,
             search_tool=search_tool,
             location_str=location_str,
         )

         valid_results = [item for item in raw_results if not item.startswith("[search-error") and item.strip()]
         evidence_snippets = [item for item in valid_results if not item.startswith("[")]
         has_realtime_evidence = len(evidence_snippets) > 0
         search_had_errors = any(item.startswith("[search-error") for item in raw_results)

         reranker = get_reranker()
         top_results = reranker.rerank(
             query=f"{domain} incident in {location_str}. {description}",
             results=valid_results if valid_results else raw_results,
             top_k=4,
         )

         numbered = "\n".join(f"[{index + 1}] {snippet}" for index, snippet in enumerate(top_results))

         prompt = f"""You are a {domain} verification agent for Poland crisis operations.
Use the curated public source catalog and open-web findings to assess credibility.

Guidelines:
1) Base assessment primarily on Search snippets evidence (if available).
2) Consider description specificity and coherence with search results.
3) Report corroborating_evidence=false if snippets are insufficient/unavailable.
4) If no snippet evidence: credibility_score should reflect description quality only.
5) Never claim certainty without supporting evidence.

Domain: {domain}
Location: {location_str}
Date: {date_str}
Description: {description}
Curated sources: {source_digest(domain)}
Suggested X tags: {social_tags(domain)}
Found {len(top_results)} relevant search results to evaluate.

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

         # Use advanced credibility model for intelligent fallback
         if not has_realtime_evidence:
             automated_score = AdvancedCredibilityModel.compute_credibility_score(
                 description=description,
                 raw_results=raw_results,
                 top_results=top_results,
                 has_search_errors=search_had_errors,
                 has_realtime_evidence=False,
             )
             automated_risk = AdvancedCredibilityModel.compute_deepfake_risk(
                 description=description,
                 top_results=top_results,
                 coherence_score=0.0,
             )

             result = {
                 "credibility_score": automated_score,
                 "deepfake_risk": automated_risk,
                 "reasoning": "Brak realtime evidence: ocena oparta na jakości indywidualnego opisu zdarzenia.",
                 "sources_found": [],
                 "key_findings": ["Brak niezaleznych dowodow w zewnetrznych zrodlach."],
                 "corroborating_evidence": False,
                 "related_categories": [],
                 "confidence": "low",
             }
             guard_info = {
                 "blocked": False,
                 "evidence_policy": {
                     "has_realtime_evidence": False,
                     "reason": "search_unavailable_or_empty",
                     "automated_model": "advanced_credibility_model",
                     "computed_score": automated_score,
                 },
             }
         else:
             try:
                 response, guard_info = await _guarded_ainvoke(llm, prompt, f"{domain}_verifier")
                 result = _parse_json(response.content)
             except Exception as exc:
                 logger.warning(f"{domain} verifier LLM error: {exc}")
                 # Fallback with intelligent scoring
                 automated_score = AdvancedCredibilityModel.compute_credibility_score(
                     description=description,
                     raw_results=valid_results,
                     top_results=top_results,
                     has_search_errors=False,
                     has_realtime_evidence=True,
                 )
                 result = {
                     "credibility_score": automated_score,
                     "deepfake_risk": 0.45,
                     "reasoning": f"Fallback z powodu bledu LLM: {exc}",
                     "sources_found": [],
                     "key_findings": ["Automatyczna weryfikacja zdegraduwana"],
                     "corroborating_evidence": len(top_results) >= 2,
                     "related_categories": [],
                     "confidence": "low",
                 }
                 guard_info = {"blocked": False}

         # Validate and bound LLM output using evidence-aware strategy
         llm_score = _as_float(result.get("credibility_score", 0.5), 0.5)
         min_bound, max_bound = estimate_llm_credibility_bounds(
             raw_results_count=len(raw_results),
             top_results_count=len(top_results),
         )

         # Apply bounds with logging for transparency
         bounded_score = max(min_bound, min(max_bound, llm_score))
         if abs(bounded_score - llm_score) > 0.05:
             logger.info(
                 f"{domain}_verifier score adjustment for consistency: "
                 f"{llm_score:.3f} -> {bounded_score:.3f} "
                 f"(bounds: {min_bound:.3f}-{max_bound:.3f}, "
                 f"results: {len(raw_results)} raw, {len(top_results)} reranked)"
             )

         result["credibility_score"] = bounded_score

          # If very low evidence, mark corroboration as false
          if len(top_results) == 0:
              result["corroborating_evidence"] = False
              result["confidence"] = "low"

          related = [_normalize_category(item) for item in _extract_related_categories(result.get("related_categories"))]
          related = [item for item in related if item not in {"unknown", domain}]

          return {
              "domain_verifications": {
                  domain: {
                      "credibility_score": _as_float(result.get("credibility_score", 0.5), 0.5),
                      "deepfake_risk": _as_float(result.get("deepfake_risk", 0.3), 0.3),
                      "reasoning": _as_str(result.get("reasoning"), ""),
                      "sources_found": _as_list_str(result.get("sources_found")),
                      "key_findings": _as_list_str(result.get("key_findings")),
                      "corroborating_evidence": bool(result.get("corroborating_evidence", False)),
                  }
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
                          "cache": cache_meta,
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
        domain_verifications = state.get("domain_verifications") or {}
        credibility = domain_verifications.get(category) or state.get("credibility_result") or {}
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

        llm_related = [_normalize_category(item) for item in _as_list_str(result.get("related_categories"))]
        merged_related = sorted(set([item for item in related + inferred + llm_related if item not in {"unknown", category}]))

        realtime_load = get_live_metrics(window_minutes=15)

        return {
            "related_categories": merged_related,
            "credibility_result": credibility,
            "cross_domain_relations": {
                "dependency_graph": result.get("dependency_graph", []),
                "operational_note": result.get("operational_note", ""),
                "analyzed_recent_incidents": len(recent_incidents),
                "domains_verified": sorted(domain_verifications.keys()),
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

         credibility_score = _as_float(credibility.get("credibility_score", 0.5), 0.5)
         deepfake_risk = _as_float(credibility.get("deepfake_risk", 0.3), 0.3)
         corroborating = credibility.get("corroborating_evidence", False)

         # Determine priority baseline based on credibility signal
         # Low credibility incidents should get P3 or P4 unless there are strong indicators
         credibility_priority_baseline = "P4_LOW"
         if credibility_score >= 0.70:
             credibility_priority_baseline = "P2_HIGH"
         elif credibility_score >= 0.50:
             credibility_priority_baseline = "P3_MEDIUM"
         elif credibility_score >= 0.30:
             credibility_priority_baseline = "P3_MEDIUM"

         # High deepfake risk should lower priority or require more evidence
         if deepfake_risk >= 0.60:
             credibility_priority_baseline = "P4_LOW"

         prompt = f"""You are a crisis prioritization officer for Polish emergency services.
Assign priority using credibility signals, incident type, load, and corroborating evidence.
All textual outputs MUST be in Polish.

IMPORTANT RULES:
1) Do NOT override credibility signals: low credibility should NOT get P1_CRITICAL
2) Corroborating evidence (multiple sources) justifies higher priority
3) High deepfake risk (>60%) suggests lower priority unless corroborated
4) Category criticality matters: cyber/terror can be P1; floods depend on scope

Assessment data:
- Category: {category}
- Related categories: {related}
- Location: {location_str}
- Description: {incident.get('description', '')}
- Credibility score: {credibility_score:.1%}
- Deepfake risk: {deepfake_risk:.1%}
- Corroborating evidence: {corroborating}
- Realtime incidents in 15m: {realtime_load.get('incidents_in_window', 0)}
- Category distribution: {realtime_load.get('category_counts', {})}
- Suggested baseline priority: {credibility_priority_baseline}

Priority scale (be conservative with high priority):
- P1_CRITICAL: Verified threat to large population or critical infrastructure
- P2_HIGH: Credible threat or confirmed incident affecting multiple systems
- P3_MEDIUM: Probable incident or lower credibility with concerning signals
- P4_LOW: Low credibility, unverified, or minor impact

Return JSON only:
{{
  "priority": "P1_CRITICAL | P2_HIGH | P3_MEDIUM | P4_LOW",
  "reasoning": "uzasadnienie po polsku",
  "recommended_actions": ["zalecenie 1", "zalecenie 2", "zalecenie 3"]
}}"""

         try:
             response, guard_info = await _guarded_ainvoke(llm, prompt, "priority_assessor")
             result = _parse_json(response.content)
         except Exception as exc:
             logger.warning(f"Priority assessor LLM error: {exc}")
             result = {
                 "priority": credibility_priority_baseline,
                 "reasoning": f"Fallback z powodu bledu LLM: {exc}. Bazowy priorytet wg wiarygodnosci.",
                 "recommended_actions": [
                     "Skierowac lokalne sluzby do obszaru zdarzenia",
                     "Uruchomic reczna weryfikacje informacji",
                     "Wydac wstepny komunikat ostrzegawczy",
                 ],
             }
             guard_info = {"blocked": False}

         # Enforce credibility-based priority sanity check
         llm_priority = result.get("priority", credibility_priority_baseline)
         priority_map = {"P1_CRITICAL": 1, "P2_HIGH": 2, "P3_MEDIUM": 3, "P4_LOW": 4}

         # Verify LLM priority doesn't contradict credibility signal
         # If low credibility (< 0.35) and high deepfake risk, cap at P3_MEDIUM
         if credibility_score < 0.35 and deepfake_risk > 0.55:
             if priority_map.get(llm_priority, 4) < 3:  # Less than P3_MEDIUM
                 llm_priority = "P3_MEDIUM"
                 logger.info(
                     f"priority_assessor: Adjusted {result.get('priority')} -> P3_MEDIUM "
                     f"due to low credibility ({credibility_score:.1%}) and high deepfake risk ({deepfake_risk:.1%})"
                 )

         # If credibility is high (>0.75) with corroborating evidence, can justify P1
         if credibility_score > 0.75 and corroborating and category in {"cyber", "terror", "infrastructure"}:
             if priority_map.get(llm_priority, 4) > 1:  # Could be lowered
                 llm_priority = "P1_CRITICAL"

         return {
             "priority": llm_priority,
             "recommended_actions": result.get("recommended_actions", []),
             "processing_log": [
                 {
                     "agent": "priority_assessor",
                     "status": "completed",
                     "timestamp": _now(),
                     "details": {
                         "priority": llm_priority,
                         "reasoning": result.get("reasoning", ""),
                         "credibility_baseline": credibility_priority_baseline,
                         "credibility_score": credibility_score,
                         "deepfake_risk": deepfake_risk,
                         "corroborating_evidence": corroborating,
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

    # Fan-out: run all verifiers in parallel; each verifier decides whether to process or skip.
    workflow.add_edge("supervisor", "flood_verifier")
    workflow.add_edge("supervisor", "cyber_verifier")
    workflow.add_edge("supervisor", "terror_verifier")
    workflow.add_edge("supervisor", "infrastructure_verifier")
    workflow.add_edge("supervisor", "traffic_verifier")

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
