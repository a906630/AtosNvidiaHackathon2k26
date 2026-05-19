"""
Prompt guardrails for LLM calls.

Primary framework: LLM Guard (open source)
- https://github.com/protectai/llm-guard

This module applies:
1) Prompt-injection scanning
2) Basic policy filtering
3) Safe fallback regex checks when LLM Guard is unavailable
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)
_llm_guard_warned = False


# Conservative patterns used by fallback checks and BanSubstrings scanner.
BLOCK_PATTERNS = [
    r"ignore\s+all\s+previous\s+instructions",
    r"system\s+prompt",
    r"developer\s+message",
    r"jailbreak",
    r"do\s+anything\s+now",
    r"reveal\s+hidden\s+rules",
    r"override\s+policy",
]


def _fallback_scan(prompt: str) -> tuple[str, bool, dict[str, Any]]:
    """Fallback scanner when LLM Guard cannot be imported."""
    lowered = prompt.lower()
    hits = [pattern for pattern in BLOCK_PATTERNS if re.search(pattern, lowered)]
    blocked = len(hits) > 0
    return prompt, not blocked, {
        "provider": "regex_fallback",
        "blocked": blocked,
        "matched_patterns": hits,
    }


def _scan_with_llm_guard(prompt: str) -> tuple[str, bool, dict[str, Any]]:
    """Try scanning with LLM Guard and gracefully fallback on API/version differences."""
    try:
        from llm_guard import scan_prompt
        from llm_guard.input_scanners import BanSubstrings, PromptInjection

        scanners = [
            PromptInjection(),
            BanSubstrings(substrings=[
                "ignore all previous instructions",
                "reveal system prompt",
                "override policy",
            ]),
        ]

        # The return signature can differ across versions.
        scan_result = scan_prompt(scanners, prompt)
        if isinstance(scan_result, tuple):
            sanitized_prompt = scan_result[0]
            is_valid = True
            scanner_info: Any = None
            if len(scan_result) > 1 and isinstance(scan_result[1], bool):
                is_valid = scan_result[1]
            if len(scan_result) > 2:
                scanner_info = scan_result[2]

            return sanitized_prompt, bool(is_valid), {
                "provider": "llm_guard",
                "blocked": not bool(is_valid),
                "scanner_info": scanner_info,
            }

        # Unknown signature; consider it pass-through.
        return prompt, True, {
            "provider": "llm_guard",
            "blocked": False,
            "scanner_info": "unknown_return_signature",
        }

    except Exception as exc:
        global _llm_guard_warned
        if not _llm_guard_warned:
            logger.warning(
                "LLM Guard unavailable or failed: %s; using regex fallback. "
                "Install dependency 'llm-guard' to enable full scanner pipeline.",
                exc,
            )
            _llm_guard_warned = True
        return _fallback_scan(prompt)


def guard_prompt(prompt: str, context: str) -> tuple[str, dict[str, Any]]:
    """Validate and sanitize prompt before LLM invocation."""
    settings = get_settings()

    if not settings.guardrails_enabled:
        return prompt, {
            "context": context,
            "guardrails_enabled": False,
            "blocked": False,
            "provider": "disabled",
        }

    sanitized_prompt, is_valid, details = _scan_with_llm_guard(prompt)
    blocked = not is_valid

    if blocked:
        logger.warning(f"Prompt blocked by guardrails in context='{context}'")

    if blocked and settings.guardrails_fail_closed:
        raise ValueError(f"Prompt blocked by policy filter in context='{context}'")

    return sanitized_prompt, {
        "context": context,
        "guardrails_enabled": True,
        "fail_closed": settings.guardrails_fail_closed,
        **details,
    }

