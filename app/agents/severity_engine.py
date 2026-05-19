"""
Deterministic severity scoring engine (wg Pydantic Agentic Crisis Management).

Oblicza severity_score na podstawie czynników infrastruktury, populacji
i czasu trwania przerwania - dając zbudowaną skalę niezależną od LLM.
"""
from app.schemas import SeverityLevel, SeverityFactors


class SeverityScoringEngine:
    """Deterministic scoring for crisis severity assessment."""

    WEIGHTING = {
        "population": 0.25,
        "infrastructure": 0.30,
        "duration": 0.15,
        "cascading": 0.20,
        "geographic": 0.10,
    }

    SEVERITY_THRESHOLDS = {
        SeverityLevel.CRITICAL: 75.0,
        SeverityLevel.HIGH: 50.0,
        SeverityLevel.MEDIUM: 25.0,
        SeverityLevel.LOW: 0.0,
    }

    @staticmethod
    def compute_score(factors: SeverityFactors) -> float:
        """
        Compute deterministic severity score (0-100).

        Wagi oparte na Dokumentu Pydantic Architecture:
         - Population impact: 25%
         - Infrastructure criticality: 30%
         - Duration (normalized to 72h): 15%
         - Cascading risk: 20%
         - Geographic scope: 10%
        """
        duration_norm = min(factors.disruption_duration_hours / 72.0, 1.0)

        score = (
            factors.normalized_population_score * SeverityScoringEngine.WEIGHTING["population"]
            + factors.infrastructure_criticality * SeverityScoringEngine.WEIGHTING["infrastructure"]
            + duration_norm * SeverityScoringEngine.WEIGHTING["duration"]
            + factors.cascading_risk * SeverityScoringEngine.WEIGHTING["cascading"]
            + factors.geographic_scope_score * SeverityScoringEngine.WEIGHTING["geographic"]
        ) * 100

        return round(score, 2)

    @staticmethod
    def score_to_severity(score: float) -> SeverityLevel:
        """Map numeric score to SeverityLevel."""
        for severity, threshold in [
            (SeverityLevel.CRITICAL, SeverityScoringEngine.SEVERITY_THRESHOLDS[SeverityLevel.CRITICAL]),
            (SeverityLevel.HIGH, SeverityScoringEngine.SEVERITY_THRESHOLDS[SeverityLevel.HIGH]),
            (SeverityLevel.MEDIUM, SeverityScoringEngine.SEVERITY_THRESHOLDS[SeverityLevel.MEDIUM]),
            (SeverityLevel.LOW, SeverityScoringEngine.SEVERITY_THRESHOLDS[SeverityLevel.LOW]),
        ]:
            if score >= threshold:
                return severity
        return SeverityLevel.LOW

    @staticmethod
    def compute_and_classify(factors: SeverityFactors) -> tuple[float, SeverityLevel]:
        """Compute score and return (score, severity_level)."""
        score = SeverityScoringEngine.compute_score(factors)
        severity = SeverityScoringEngine.score_to_severity(score)
        return score, severity

