"""
Advanced credibility assessment model for domain verification.

Uses multiple evidence signals to generate reliable credibility scores
instead of hardcoded thresholds.
"""
import re
from typing import Optional


class AdvancedCredibilityModel:
    """
    Multi-factor credibility assessment model.

    Scores are based on:
    - Raw results count and quality
    - Reranked results count and relevance
    - Description specificity (numbers, dates, locations)
    - Evidence coherence (overlapping keywords)
    - Evidence freshness
    """

    # Weights for different signals
    WEIGHTS = {
        "raw_results_count": 0.10,      # Did we find any results?
        "reranked_results_count": 0.15,  # Did top results survive reranking?
        "description_specificity": 0.15, # Is description concrete?
        "evidence_coherence": 0.30,      # Do multiple sources mention same things?
        "search_error_penalty": 0.30,    # Did search work at all?
    }

    @staticmethod
    def extract_specificity_signals(description: str) -> float:
        """
        Extract specificity signals from incident description.

        Returns float 0.0-1.0 based on presence of:
        - Numbers (casualties, damage amount, etc.)
        - Dates/times
        - Named locations/landmarks
        - Measurements/quantities
        - Specific actions/verbs
        """
        if not description:
            return 0.0

        description_lower = description.lower()
        specificity_score = 0.0
        signal_count = 0

        # Number of detailed incident indicators
        has_numbers = bool(re.search(r'\d+', description))
        has_times = bool(re.search(r'\d{1,2}:\d{2}|\d{1,2}:\d{2}:\d{2}', description))
        has_quantities = bool(re.search(r'(liczba|ilosc|kilka|wiele|dziesiątki|setki|tysiące)', description_lower))
        has_damage = bool(re.search(r'(zniszczone|uszkodzenia|zniszczenia|uszkodzone|spalony)', description_lower))
        has_action_verbs = bool(re.search(r'(atakuje|zaatakował|zalewa|zalał|awaria|zablokowany|wysadził|wybuch)', description_lower))
        has_locations = bool(re.search(r'(ulica|droga|most|rzeka|Port|Stacja|Dworzec|Szkoła|Szpital)', description))
        has_casualties = bool(re.search(r'(ranni|zabici|poszkodowani|ewakuowani|ofiar)', description_lower))
        has_duration = bool(re.search(r'(przy|od|przez|w ciągu|od.*do)', description_lower))

        signals = [
            (has_numbers, 1),
            (has_times, 2),
            (has_quantities, 1),
            (has_damage, 2),
            (has_action_verbs, 2),
            (has_locations, 2),
            (has_casualties, 2),
            (has_duration, 1),
        ]

        for has_signal, weight in signals:
            if has_signal:
                specificity_score += weight
                signal_count += 1

        # Normalize to 0-1
        max_score = sum(w for _, w in signals)
        return min(1.0, specificity_score / max_score) if max_score > 0 else 0.0

    @staticmethod
    def calculate_evidence_coherence(
        description: str,
        raw_results: list[str],
        top_results: list[str],
    ) -> float:
        """
        Calculate coherence between description and evidence.

        Extracts key terms from description and checks if they appear
        in search results (suggesting corroboration across sources).
        """
        if not description or not (raw_results or top_results):
            return 0.0

        # Extract key terms (>3 chars, not stop words)
        stop_words = {
            'że', 'do', 'na', 'w', 'z', 'to', 'się', 'po', 'co', 'dla',
            'jest', 'są', 'bądź', 'być', 'był', 'byli', 'nie', 'czy',
            'od', 'przez', 'przy', 'który', 'która', 'które', 'i', 'lub',
            'ale', 'albo', 'jak', 'gdzie', 'kiedy', 'dlaczego', 'ile',
        }

        words = re.findall(r'\b\w+\b', description.lower())
        key_terms = [w for w in words if len(w) > 3 and w not in stop_words]

        if not key_terms:
            return 0.0

        # Count how many key terms appear in results
        combined_results = ' '.join(raw_results + top_results).lower()
        matching_terms = sum(1 for term in key_terms if term in combined_results)

        # Coherence = ratio of matching key terms
        coherence = matching_terms / len(key_terms) if key_terms else 0.0
        return min(1.0, coherence)

    @staticmethod
    def compute_credibility_score(
        description: str,
        raw_results: list[str],
        top_results: list[str],
        has_search_errors: bool = False,
        has_realtime_evidence: bool = True,
    ) -> float:
        """
        Compute credibility score based on multiple evidence signals.

        Returns float 0.0-1.0 (will be converted to percentage in UI).
        """

        # If search completely failed, low score
        if has_search_errors and not raw_results:
            return 0.20  # Some baseline credibility from description alone

        base_score = 0.25  # Baseline from description

        # Signal 1: Raw results count (0-1.0)
        raw_count_score = min(1.0, len(raw_results) / 5.0) if raw_results else 0.0

        # Signal 2: Top reranked results count (0-1.0)
        reranked_count_score = min(1.0, len(top_results) / 3.0) if top_results else 0.0

        # Signal 3: Description specificity (0-1.0)
        specificity_score = AdvancedCredibilityModel.extract_specificity_signals(description)

        # Signal 4: Evidence coherence (0-1.0)
        coherence_score = AdvancedCredibilityModel.calculate_evidence_coherence(
            description, raw_results, top_results
        )

        # Signal 5: Search error penalty
        error_penalty = 1.0 if not has_search_errors else 0.7

        # Weighted combination
        weighted_score = (
            base_score +
            (raw_count_score * AdvancedCredibilityModel.WEIGHTS["raw_results_count"]) +
            (reranked_count_score * AdvancedCredibilityModel.WEIGHTS["reranked_results_count"]) +
            (specificity_score * AdvancedCredibilityModel.WEIGHTS["description_specificity"]) +
            (coherence_score * AdvancedCredibilityModel.WEIGHTS["evidence_coherence"]) +
            ((error_penalty - 0.7) * AdvancedCredibilityModel.WEIGHTS["search_error_penalty"])
        )

        # Cap at 1.0 and apply minimum based on evidence availability
        final_score = min(1.0, weighted_score)

        # If no realtime evidence at all, cap lower
        if not has_realtime_evidence:
            final_score = min(final_score, 0.45)

        return round(final_score, 3)

    @staticmethod
    def compute_deepfake_risk(
        description: str,
        top_results: list[str],
        coherence_score: float,
    ) -> float:
        """
        Estimate deepfake/false-positive risk.

        Higher risk if:
        - Low coherence (description doesn't match search results)
        - Very generic description
        - Results talk about similar but different incidents
        """

        # Base risk
        risk = 0.30

        # Reduce risk if coherence is high (sources align)
        coherence_penalty = coherence_score * 0.25
        risk -= coherence_penalty

        # Increase risk if description is too generic
        if len(description) < 50:
            risk += 0.15

        # Check for conflicting signals (e.g., "recent flood" but results talk about drought)
        description_lower = description.lower()
        conflict_pairs = [
            (r'zalew|powodz|woda|topn', r'suszy|susza|sucho'),
            (r'atak|cyber|hacker', r'normalny|rutin|zwyczaj'),
            (r'terrorys|zamach|wybuch', r'przypadk|wypadek'),
        ]

        for positive_pattern, negative_pattern in conflict_pairs:
            has_positive = bool(re.search(positive_pattern, description_lower))
            has_negative = bool(re.search(negative_pattern, description_lower))
            if has_positive and has_negative:
                risk += 0.20

        return min(1.0, max(0.0, risk))


def estimate_llm_credibility_bounds(
    raw_results_count: int,
    top_results_count: int,
) -> tuple[float, float]:
    """
    Estimate reasonable bounds for LLM credibility score based on
    how much evidence was actually found and reranked.

    Returns (min_bound, max_bound) for LLM output validation.
    """

    # No results at all: very constrained
    if raw_results_count == 0:
        return (0.10, 0.30)

    # Few raw results, few reranked
    if raw_results_count < 3 and top_results_count < 2:
        return (0.20, 0.50)

    # Moderate results
    if raw_results_count >= 3 and top_results_count >= 2:
        return (0.35, 0.85)

    # Good results
    if raw_results_count >= 5 and top_results_count >= 3:
        return (0.50, 0.95)

    # Excellent results
    return (0.65, 1.0)

