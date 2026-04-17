"""Versioned LLM rate card.

Prices are per 1 million tokens, USD. Bump PRICING_VERSION whenever
a rate changes so historical rows remain priced at the rate in force
at the time of the call. Unknown model names price to 0 and log once.

When adding a new model, include a source URL comment so the rate
can be verified later.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TypedDict

log = logging.getLogger(__name__)

PRICING_VERSION = "v2026-04-18"


class Rate(TypedDict):
    input: float
    output: float
    cached: float


# USD per 1M tokens. Preview models assume parity with their stable
# counterpart until Google publishes separate rates — revise here if
# the actual invoice diverges.
RATES: dict[str, Rate] = {
    # https://ai.google.dev/gemini-api/docs/pricing
    "gemini-2.5-flash":       {"input": 0.30, "output": 2.50,  "cached": 0.075},
    "gemini-3-flash-preview": {"input": 0.30, "output": 2.50,  "cached": 0.075},
    "gemini-3-pro-preview":   {"input": 2.00, "output": 12.00, "cached": 0.50},
    "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00, "cached": 0.50},
    # https://platform.claude.com/docs/en/about-claude/pricing — wired when
    # a ClaudeProvider lands:
    # "claude-haiku-4-5":       {"input": 1.00, "output": 5.00,  "cached": 0.10},
    # "claude-sonnet-4-6":      {"input": 3.00, "output": 15.00, "cached": 0.30},
    # "claude-opus-4-7":        {"input": 5.00, "output": 25.00, "cached": 0.50},
}

_PER_MILLION = Decimal("1000000")
_warned_models: set[str] = set()


def compute_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
) -> Decimal:
    """Return USD cost for a single call. 0 for unknown models."""
    rate = RATES.get(model)
    if rate is None:
        if model not in _warned_models:
            log.warning("No pricing entry for model %r — cost will be 0", model)
            _warned_models.add(model)
        return Decimal(0)

    # Cached tokens are a subset of input tokens on some providers
    # (Gemini) and a separate bucket on others (Claude cache reads).
    # We bill them at the cached rate and the remainder at the input
    # rate — leaving the caller to pass a correct split.
    billable_input = max(input_tokens - cached_tokens, 0)

    total = (
        Decimal(str(rate["input"]))   * Decimal(billable_input)
        + Decimal(str(rate["cached"])) * Decimal(cached_tokens)
        + Decimal(str(rate["output"])) * Decimal(output_tokens)
    ) / _PER_MILLION

    return total.quantize(Decimal("0.000001"))
