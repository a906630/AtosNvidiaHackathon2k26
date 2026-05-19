from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class CrisisCategory(str, Enum):
    FLOOD = "flood"
    CYBER = "cyber"
    TERROR = "terror"
    INFRASTRUCTURE = "infrastructure"
    TRAFFIC = "traffic"
    SERVICES = "services"
    UNKNOWN = "unknown"


class SourceType(str, Enum):
    CITIZEN = "citizen"
    SENSOR = "sensor"
    SOCIAL_MEDIA = "social_media"
    INSTITUTION = "institution"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Location(StrictModel):
    voivodeship: str = Field(..., examples=["dolnoslaskie"])
    county: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("county", "powiat"),
        serialization_alias="county",
        examples=["wroclawski"],
    )
    municipality: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("municipality", "gmina"),
        serialization_alias="municipality",
        examples=["Wroclaw"],
    )
    coordinates: Optional[dict[str, float]] = Field(None, examples=[{"lat": 51.1, "lon": 17.0}])


class MediaRef(StrictModel):
    type: str = Field(..., examples=["image"])
    url: str = Field(..., examples=["https://example.com/photo.jpg"])


class IncidentSource(StrictModel):
    type: SourceType
    reporter_id: Optional[str] = None
    channel: Optional[str] = Field(None, examples=["web"])


class IncidentInput(StrictModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    location: Location
    category_hint: CrisisCategory = CrisisCategory.UNKNOWN
    description: str = Field(..., min_length=10, examples=["Main street is flooded and water level keeps rising."])
    source: IncidentSource
    media_refs: list[MediaRef] = Field(default_factory=list)


class IncidentResponse(StrictModel):
    incident_id: str
    status: str = "processing"
    stream_url: str
    result_url: str


class CredibilityResult(StrictModel):
    credibility_score: float
    deepfake_risk: float
    reasoning: str
    sources_found: list[str]
    key_findings: list[str]
    corroborating_evidence: bool


class ProcessingStep(StrictModel):
    agent: str
    status: str
    timestamp: str
    details: dict[str, Any]


class RealtimeLoad(StrictModel):
    total_incidents: int
    active_processing: int
    completed: int
    recent_window_minutes: int
    incidents_in_window: int
    category_counts: dict[str, int] = Field(default_factory=dict)
    ingestion_rate_by_minute: dict[str, int] = Field(default_factory=dict)
    generated_at: str


class IncidentResult(StrictModel):
    incident_id: str
    category: str
    related_categories: list[str] = Field(default_factory=list)
    credibility: Optional[CredibilityResult] = None
    priority: str
    recommended_actions: list[str] = Field(default_factory=list)
    service_message: str
    citizen_message: str
    human_review_required: bool
    realtime_load: RealtimeLoad
    processing_log: list[ProcessingStep] = Field(default_factory=list)
    completed_at: str


class IncidentListItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    incident_id: str
    timestamp: Optional[str] = None
    category_hint: Optional[str] = None
    description: Optional[str] = None
    source: Optional[IncidentSource] = None
    location: Optional[Location] = None
    result: Optional[IncidentResult] = None


class MermaidGraphResponse(StrictModel):
    mermaid: str


class GraphJsonResponse(StrictModel):
    nodes: list[str] = Field(default_factory=list)
    edges: list[dict[str, str]] = Field(default_factory=list)


class GraphRunPreviewResponse(StrictModel):
    incident_id: str
    status: str
    result: Optional[IncidentResult] = None
    message: Optional[str] = None


class SseEventPayload(StrictModel):
    type: str
    node: Optional[str] = None
    description: Optional[str] = None
    timestamp: str
    data: dict[str, Any] = Field(default_factory=dict)


# --- Formalne modele z Pydantic Agentic Crisis Management ---


class SeverityLevel(str, Enum):
    """Formalna ranga ważności incydentu (wg dokumentu Pydantic Architecture)."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class VerificationStatus(str, Enum):
    """Status weryfikacji incydentu."""
    UNVERIFIED = "unverified"
    PROBABLE = "probable"
    VERIFIED = "verified"
    FALSE_POSITIVE = "false_positive"


class SeverityFactors(StrictModel):
    """Czynniki wpływające na stopień ważności (deterministyczne scoring)."""
    affected_population: int = Field(ge=0, description="Liczba dotkniętych osób")
    normalized_population_score: float = Field(ge=0.0, le=1.0, description="Score populacji (0-1)")
    infrastructure_criticality: float = Field(ge=0.0, le=1.0, description="Krytyczność infrastruktury (0-1)")
    disruption_duration_hours: float = Field(ge=0, description="Oczekiwany czas przerwania")
    cascading_risk: float = Field(ge=0.0, le=1.0, description="Ryzyko efektu kaskadowego (0-1)")
    economic_impact_estimate_eur: float = Field(ge=0, description="Wpływ ekonomiczny w EUR")
    geographic_scope_score: float = Field(ge=0.0, le=1.0, description="Zasięg geograficzny (0-1)")


class CascadingImpact(StrictModel):
    """Prognoza wpływu kaskadowego na inne systemy."""
    affected_system: str
    probability: float = Field(ge=0.0, le=1.0, description="Prawdopodobieństwo (0-1)")
    estimated_time_minutes: int = Field(ge=0, description="Szacowany czas w minutach")
    severity: SeverityLevel
    dependency_path: list[str] = Field(default_factory=list, description="Ścieżka zależności")
    geographic_regions: list[str] = Field(default_factory=list, description="Dotkniętych regiony")
    criticality_rank: int = Field(ge=1, le=10, description="Ranga krytyczności (1-10)")
    confidence_interval_low: float = Field(ge=0.0, le=1.0)
    confidence_interval_high: float = Field(ge=0.0, le=1.0)


class Recommendation(StrictModel):
    """Zalecenie operacyjne z wymaganym zatwierdzeniem."""
    action: str = Field(..., description="Konkretne działanie do wykonania")
    rationale: str = Field(..., description="Uzasadnienie rekomendacji")
    priority: int = Field(ge=1, le=5, description="Priorytet (1=najwyższy)")
    requires_human_approval: bool = Field(default=True, description="Czy wymaga zatwierdzenia człowieka")
    estimated_duration_minutes: Optional[int] = None


class HumanApproval(StrictModel):
    """Formalne zatwierdzenie przez operatora/decydenta."""
    incident_id: str
    approver_id: str
    approver_role: str = Field(..., description="Rola zatwierdającego (operator, manager)")
    approved: bool
    decision_notes: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    digital_signature: Optional[str] = None


class SituationReport(StrictModel):
    """Executive summary operacyjny (SITREP) do podejmowania decyzji."""
    incident_id: str
    executive_summary: str
    current_status: str
    emerging_risks: list[str] = Field(default_factory=list)
    unresolved_decisions: list[str] = Field(default_factory=list)
    recommended_actions_awaiting_approval: list[str] = Field(default_factory=list)
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
