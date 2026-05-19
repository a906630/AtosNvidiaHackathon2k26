from typing import TypedDict, Annotated, Optional
from operator import add


def merge_dicts(a: dict | None, b: dict | None) -> dict:
    """Reducer for parallel nodes: merge dictionaries instead of overwriting."""
    return {**(a or {}), **(b or {})}


class ProcessingStep(TypedDict):
    agent: str
    status: str
    timestamp: str
    details: dict


class IncidentState(TypedDict):
    # Input payload
    incident_data: dict

    # Router output
    category: str
    related_categories: list[str]
    selected_domains: list[str]
    recent_incidents: list[dict]

    # Output from domain verifiers.
    credibility_result: Optional[dict]
    domain_verifications: Annotated[dict[str, dict], merge_dicts]

    # Output from correlation and prioritization.
    cross_domain_relations: dict
    realtime_load: dict
    priority: Optional[str]
    recommended_actions: list[str]

    # Output from communication node.
    service_message: Optional[str]
    citizen_message: Optional[str]
    human_review_required: bool

    # add() merges arrays returned by every node.
    processing_log: Annotated[list[ProcessingStep], add]

    error: Optional[str]
