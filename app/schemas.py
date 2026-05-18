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
