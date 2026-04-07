"""LLM provider protocol and factory.

Thin abstraction over LLM SDKs. Currently supports Gemini (google-genai).
Designed so additional providers (Claude, OpenAI) can be added by implementing
the LLMProvider protocol.
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """Minimal contract for an LLM provider."""

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        response_schema: type | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        grounding: bool = False,
    ) -> dict[str, Any]:
        """Generate a response.

        Args:
            prompt: User prompt text.
            system: Optional system instruction.
            response_schema: Pydantic model or dict for structured JSON output.
            temperature: Sampling temperature (0-1).
            max_tokens: Max output tokens.
            grounding: Enable web-search grounding (Gemini-specific).

        Returns:
            {"text": str, "parsed": dict | list | None, "usage": dict}
        """
        ...

    @property
    def model_name(self) -> str: ...


def get_provider(name: str = "gemini", model: str | None = None) -> LLMProvider:
    """Factory. Reads API key from env vars.

    Args:
        name: Provider name ("gemini").
        model: Model override (e.g. "gemini-3.0-flash").
    """
    if name == "gemini":
        from pipeline.llm.gemini import GeminiProvider

        return GeminiProvider(model=model)

    raise ValueError(f"Unknown LLM provider: {name!r}. Available: gemini")
