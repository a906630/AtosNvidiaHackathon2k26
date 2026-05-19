"""
Advanced credibility assessment model for domain verification.

Uses multiple evidence signals to generate reliable credibility scores
instead of hardcoded thresholds.

Philosophy: START SKEPTICAL. Every incident is unverified until proven otherwise.
Credibility must be EARNED through independent corroboration, not assumed.
"""
import re
from typing import Optional


class AdvancedCredibilityModel:
    """
    Multi-factor credibility assessment model.

    Scores are based on:
    - Independent evidence corroboration (not just keyword echo)
    - Reranked results quality and diversity
    - Description specificity (numbers, dates, locations)
    - Source diversity (multiple independent sources)
    - Evidence freshness and relevance
    """

    # Weights for different signals — evidence-heavy, description-light
    WEIGHTS = {
        "raw_results_count": 0.08,       # Did we find any results?
        "reranked_results_count": 0.12,   # Did top results survive reranking?
        "description_specificity": 0.10,  # Is description concrete? (LOW weight — easy to fake)
        "evidence_coherence": 0.35,       # Do multiple INDEPENDENT sources corroborate?
        "source_diversity": 0.15,         # Are results from different sources?
        "search_error_penalty": 0.20,     # Did search work at all?
    }

    @staticmethod
    def extract_specificity_signals(description: str) -> float:
        """
        Extract specificity signals from incident description.

        Returns float 0.0-1.0 based on presence of concrete details.
        NOTE: Specificity alone does NOT equal credibility — fabricated reports
        can be highly specific. This signal has LOW weight in final score.
        """
        if not description:
            return 0.0

        description_lower = description.lower()

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

        specificity_score = sum(weight for has_signal, weight in signals if has_signal)
        max_score = sum(w for _, w in signals)
        return min(1.0, specificity_score / max_score) if max_score > 0 else 0.0

    @staticmethod
    def _extract_key_terms(text: str) -> set[str]:
        """Extract meaningful key terms from text, filtering stop words."""
        stop_words = {
            'że', 'do', 'na', 'w', 'z', 'to', 'się', 'po', 'co', 'dla',
            'jest', 'są', 'bądź', 'być', 'był', 'byli', 'nie', 'czy',
            'od', 'przez', 'przy', 'który', 'która', 'które', 'i', 'lub',
            'ale', 'albo', 'jak', 'gdzie', 'kiedy', 'dlaczego', 'ile',
            'tego', 'tej', 'ten', 'tym', 'tych', 'tam', 'tutaj', 'też',
            'tylko', 'jeszcze', 'już', 'bardzo', 'może', 'tak', 'więc',
            'about', 'the', 'and', 'for', 'with', 'from', 'that', 'this',
            'was', 'were', 'are', 'has', 'have', 'been', 'will', 'would',
            'incident', 'event', 'situation', 'report', 'crisis',
        }
        words = re.findall(r'\b\w+\b', text.lower())
        return {w for w in words if len(w) > 3 and w not in stop_words}

    @staticmethod
    def _filter_valid_results(results: list[str]) -> list[str]:
        """Filter out error messages and noise from search results."""
        return [
            r for r in results
            if r.strip()
            and not r.startswith("[search-error")
            and not r.startswith("[search-tool")
            and len(r.strip()) > 20  # Skip very short snippets (likely noise)
        ]

    @staticmethod
    def calculate_evidence_coherence(
        description: str,
        raw_results: list[str],
        top_results: list[str],
    ) -> float:
        """
        Calculate INDEPENDENT corroboration between description and evidence.

        CRITICAL: Search results often echo the query terms (because the query
        was derived from the description). True corroboration requires results
        to contain ADDITIONAL specific details not present in the description,
        or to come from clearly independent/authoritative sources.
        """
        if not description:
            return 0.0

        valid_raw = AdvancedCredibilityModel._filter_valid_results(raw_results)
        valid_top = AdvancedCredibilityModel._filter_valid_results(top_results)

        if not valid_raw and not valid_top:
            return 0.0

        desc_terms = AdvancedCredibilityModel._extract_key_terms(description)
        if not desc_terms:
            return 0.0

        # Check each result individually for term overlap
        all_results = valid_top if valid_top else valid_raw
        result_scores: list[float] = []

        for result_text in all_results:
            result_terms = AdvancedCredibilityModel._extract_key_terms(result_text)
            if not result_terms:
                continue

            # Overlap: how many description terms appear in this result
            overlap = desc_terms & result_terms
            overlap_ratio = len(overlap) / len(desc_terms) if desc_terms else 0.0

            # NEW information: terms in result NOT in description (independent info)
            new_info = result_terms - desc_terms
            new_info_ratio = len(new_info) / max(len(result_terms), 1)

            # Good corroboration = moderate overlap + significant new information
            # Pure echo (high overlap, no new info) = low corroboration
            if overlap_ratio > 0.1 and new_info_ratio > 0.3:
                # Result contains related content AND adds new details
                result_scores.append(min(1.0, overlap_ratio * 0.5 + new_info_ratio * 0.5))
            elif overlap_ratio > 0.3:
                # Some overlap but might just be echoing the query
                result_scores.append(overlap_ratio * 0.25)
            else:
                result_scores.append(0.0)

        if not result_scores:
            return 0.0

        # Average of top results, but penalize if only 1 source
        avg_score = sum(sorted(result_scores, reverse=True)[:3]) / min(3, len(result_scores))

        # Source diversity bonus: more corroborating results = more trustworthy
        diversity_bonus = min(0.15, len([s for s in result_scores if s > 0.1]) * 0.05)

        return min(1.0, avg_score + diversity_bonus)

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

        Philosophy: START LOW, EARN TRUST.
        Base score is near zero. Only independent evidence raises credibility.
        """

        # Filter noise from results
        valid_raw = AdvancedCredibilityModel._filter_valid_results(raw_results)
        valid_top = AdvancedCredibilityModel._filter_valid_results(top_results)

        # If search completely failed, very low score
        if has_search_errors and not valid_raw:
            return 0.10  # Minimal baseline — we know nothing

        # START LOW: unverified report baseline
        base_score = 0.10

        # Signal 1: Valid raw results count (0-1.0)
        raw_count_score = min(1.0, len(valid_raw) / 6.0)

        # Signal 2: Top reranked results count (0-1.0)
        reranked_count_score = min(1.0, len(valid_top) / 4.0)

        # Signal 3: Description specificity (0-1.0) — low weight, easy to fake
        specificity_score = AdvancedCredibilityModel.extract_specificity_signals(description)

        # Signal 4: Evidence coherence — the MAIN signal (0-1.0)
        coherence_score = AdvancedCredibilityModel.calculate_evidence_coherence(
            description, raw_results, top_results
        )

        # Signal 5: Source diversity (unique meaningful results)
        unique_snippets = set()
        for r in valid_top:
            # Use first 80 chars as fingerprint to detect duplicates
            unique_snippets.add(r[:80].lower().strip())
        diversity_score = min(1.0, len(unique_snippets) / 3.0)

        # Signal 6: Search error penalty
        error_multiplier = 1.0 if not has_search_errors else 0.6

        weights = AdvancedCredibilityModel.WEIGHTS

        # Weighted combination (additive on top of low base)
        evidence_score = (
            (raw_count_score * weights["raw_results_count"]) +
            (reranked_count_score * weights["reranked_results_count"]) +
            (specificity_score * weights["description_specificity"]) +
            (coherence_score * weights["evidence_coherence"]) +
            (diversity_score * weights["source_diversity"])
        ) * error_multiplier

        final_score = base_score + evidence_score

        # Hard caps based on evidence availability
        if not has_realtime_evidence:
            # No independent evidence at all: cap at 0.25 max
            final_score = min(final_score, 0.25)
        elif len(valid_top) == 0:
            # Had search but no relevant results survived reranking
            final_score = min(final_score, 0.30)
        elif len(valid_top) == 1:
            # Only one source: limited corroboration
            final_score = min(final_score, 0.50)

        return round(min(1.0, final_score), 3)

    @staticmethod
    def compute_deepfake_risk(
        description: str,
        top_results: list[str],
        coherence_score: float,
    ) -> float:
        """
        Estimate deepfake/false-positive risk.

        START HIGH (skeptical). Risk decreases only with strong evidence.
        """
        valid_top = AdvancedCredibilityModel._filter_valid_results(top_results)

        # Start skeptical
        risk = 0.55

        # Reduce risk proportionally to coherence (strong corroboration = less risk)
        risk -= coherence_score * 0.30

        # Reduce risk if multiple independent results exist
        if len(valid_top) >= 3:
            risk -= 0.10
        elif len(valid_top) >= 1:
            risk -= 0.05

        # Increase risk if description is too generic
        if len(description) < 50:
            risk += 0.20
        elif len(description) < 100:
            risk += 0.10

        # Increase risk for very short or no results
        if len(valid_top) == 0:
            risk += 0.15

        # Check for conflicting signals
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

        return round(min(1.0, max(0.05, risk)), 3)


def estimate_llm_credibility_bounds(
    raw_results_count: int,
    top_results_count: int,
) -> tuple[float, float]:
    """
    Estimate reasonable bounds for LLM credibility score based on
    how much evidence was actually found and reranked.

    These bounds CONSTRAIN the LLM output to prevent hallucinated confidence.
    Philosophy: without strong evidence, LLM cannot claim high credibility.
    """

    # No results at all: LLM has nothing to base credibility on
    if raw_results_count == 0:
        return (0.05, 0.20)

    # Very few raw results, almost nothing reranked
    if raw_results_count < 3 and top_results_count < 2:
        return (0.10, 0.35)

    # Some results but limited reranking
    if raw_results_count >= 3 and top_results_count < 2:
        return (0.15, 0.45)

    # Moderate results with decent reranking
    if raw_results_count >= 3 and top_results_count >= 2:
        return (0.20, 0.65)

    # Good results with strong reranking
    if raw_results_count >= 5 and top_results_count >= 3:
        return (0.30, 0.80)

    # Excellent results
    if raw_results_count >= 8 and top_results_count >= 4:
        return (0.40, 0.90)

    return (0.15, 0.50)
