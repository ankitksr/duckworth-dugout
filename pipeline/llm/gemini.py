"""Gemini LLM provider using the google-genai SDK.

Supports structured output (via response_schema) and Google Search
grounding. Rate-limited and retried with exponential backoff.
"""

import asyncio
import json
import time
from typing import Any

from rich.console import Console

from pipeline.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_VERTEX,
    LLM_MAX_RETRIES,
    LLM_RATE_LIMIT_RPM,
)

console = Console()

# Retry-able HTTP status codes (from Gemini API)
_RETRYABLE_ERRORS = ("429", "500", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE")


def _coerce_schema(schema: Any, raw: Any) -> Any:
    """Validate raw JSON through a Pydantic schema, then dump to plain Python.

    Gemini structured-output returns raw JSON that satisfies the schema's
    *shape*, but omitted optional fields arrive missing rather than
    defaulted — so a `Field(default="")` on the schema never fires. Running
    the value through a TypeAdapter fills in defaults and runs any
    field_validator normalizers. We dump back to dicts/lists so downstream
    consumers that use `parsed.get(...)` keep working unchanged.

    Fails open: if validation raises (e.g. LLM returned extra fields that
    strict mode rejects), we return the raw parse so the caller can still
    use the response.
    """
    try:
        from pydantic import TypeAdapter
        adapter = TypeAdapter(schema)
        validated = adapter.validate_python(raw)
        return adapter.dump_python(validated, mode="python")
    except Exception:
        return raw


class GeminiProvider:
    """Gemini provider wrapping the google-genai SDK."""

    def __init__(self, model: str | None = None, *, panel: str | None = None):
        from google import genai

        api_key = GEMINI_API_KEY
        if not api_key:
            raise ValueError(
                "CT_LLM_API_KEY not set. "
                "For GCP credits, also set CT_LLM_VERTEX=1."
            )

        # Vertex AI express mode uses GCP credits; plain API key does not
        if GEMINI_VERTEX:
            self._client = genai.Client(vertexai=True, api_key=api_key)
        else:
            self._client = genai.Client(api_key=api_key)

        self._model = model or GEMINI_MODEL
        self._panel = panel or "unknown"
        self._min_interval = 60.0 / LLM_RATE_LIMIT_RPM
        self._last_call: float = 0.0

    @property
    def model_name(self) -> str:
        return self._model

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        response_schema: type | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        grounding: bool = False,
        sub_key: str | None = None,
    ) -> dict[str, Any]:
        """Generate a response from Gemini.

        Uses the synchronous client wrapped in asyncio.to_thread for
        compatibility with the async pipeline pattern.
        """
        from google.genai import types

        # Build config
        config_kwargs: dict[str, Any] = {
            "temperature": temperature,
            # Disable thinking to prevent it eating the output token budget.
            # Some models (e.g. gemini-3-pro-preview) don't support budget=0,
            # so we set a minimal budget instead.
            "thinking_config": types.ThinkingConfig(thinking_budget=128),
        }

        if max_tokens is not None:
            config_kwargs["max_output_tokens"] = max_tokens

        if response_schema is not None:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = response_schema

        if grounding:
            config_kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]

        config = types.GenerateContentConfig(
            system_instruction=system,
            **config_kwargs,
        )

        # Rate limiting + retry loop
        last_error = None
        started = time.monotonic()
        retries = 0
        for attempt in range(LLM_MAX_RETRIES + 1):
            # Rate limit
            await self._rate_limit()

            try:
                response = await asyncio.to_thread(
                    self._client.models.generate_content,
                    model=self._model,
                    contents=prompt,
                    config=config,
                )

                # Extract text
                text = response.text or ""

                # Parse structured output if schema was provided.
                # When the schema is a Pydantic model (or list[BaseModel]),
                # run the raw JSON through a TypeAdapter so Field(default=...)
                # values fire for omitted keys and any @field_validator
                # normalizers run. Downstream consumers expect dicts/lists, so
                # we dump back to native Python after validation. Validation
                # failure falls back to the raw parse rather than discarding
                # the response.
                parsed = None
                if response_schema is not None and text:
                    try:
                        raw = json.loads(text)
                    except json.JSONDecodeError:
                        raw = None
                    if raw is not None:
                        parsed = _coerce_schema(response_schema, raw)

                # Usage stats
                usage = {}
                if response.usage_metadata:
                    usage = {
                        "input_tokens": response.usage_metadata.prompt_token_count or 0,
                        "output_tokens": response.usage_metadata.candidates_token_count or 0,
                    }

                self._record_usage(
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    tool_rounds=1,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    retries=retries,
                    success=True,
                    sub_key=sub_key,
                )
                return {"text": text, "parsed": parsed, "usage": usage}

            except Exception as e:
                last_error = e
                error_str = str(e)

                # Check if retryable
                is_retryable = any(code in error_str for code in _RETRYABLE_ERRORS)
                if not is_retryable or attempt >= LLM_MAX_RETRIES:
                    self._record_usage(
                        latency_ms=int((time.monotonic() - started) * 1000),
                        retries=retries,
                        success=False,
                        error=error_str[:500],
                        sub_key=sub_key,
                    )
                    raise

                retries += 1
                # Exponential backoff
                wait = min(2 ** attempt * 2, 30)
                console.print(
                    f"  [yellow]Gemini error (attempt {attempt + 1}): {error_str[:80]}. "
                    f"Retrying in {wait}s...[/]"
                )
                await asyncio.sleep(wait)

        raise last_error  # type: ignore[misc]

    async def generate_with_tools(
        self,
        prompt: str,
        *,
        system: str | None = None,
        tools: list | None = None,
        tool_executor: Any = None,
        temperature: float = 0.7,
        max_rounds: int = 5,
        sub_key: str | None = None,
    ) -> dict[str, Any]:
        """Generate with function-calling tool use.

        Runs a multi-turn loop: the model may request tool calls,
        we execute them via tool_executor(name, args) and feed results
        back until the model produces a final text response.

        Cannot be combined with response_schema (Gemini limitation).
        """
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            thinking_config=types.ThinkingConfig(thinking_budget=128),
            tools=tools or [],
        )

        # Build initial contents
        contents: list = [types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt)],
        )]

        total_usage = {"input_tokens": 0, "output_tokens": 0}
        started = time.monotonic()
        rounds_run = 0

        try:
            for _round in range(max_rounds):
                rounds_run += 1
                await self._rate_limit()

                response = await asyncio.to_thread(
                    self._client.models.generate_content,
                    model=self._model,
                    contents=contents,
                    config=config,
                )

                if response.usage_metadata:
                    total_usage["input_tokens"] += (
                        response.usage_metadata.prompt_token_count or 0
                    )
                    total_usage["output_tokens"] += (
                        response.usage_metadata.candidates_token_count or 0
                    )

                # Check for function calls in the response
                candidate = response.candidates[0] if response.candidates else None
                if not candidate or not candidate.content or not candidate.content.parts:
                    break

                function_calls = [
                    p for p in candidate.content.parts if p.function_call
                ]

                if not function_calls:
                    # No tool calls — model is done, extract text
                    text = response.text or ""
                    parsed = None
                    try:
                        parsed = json.loads(text)
                    except (json.JSONDecodeError, ValueError):
                        pass
                    self._record_usage(
                        input_tokens=total_usage["input_tokens"],
                        output_tokens=total_usage["output_tokens"],
                        tool_rounds=rounds_run,
                        latency_ms=int((time.monotonic() - started) * 1000),
                        success=True,
                        sub_key=sub_key,
                    )
                    return {"text": text, "parsed": parsed, "usage": total_usage}

                # Execute tool calls and build responses
                contents.append(candidate.content)

                response_parts = []
                for part in function_calls:
                    fc = part.function_call
                    tool_result = (
                        tool_executor(fc.name, dict(fc.args))
                        if tool_executor
                        else {"error": "no executor"}
                    )
                    response_parts.append(types.Part.from_function_response(
                        name=fc.name,
                        response=tool_result,
                    ))

                contents.append(types.Content(
                    role="user",
                    parts=response_parts,
                ))
        except Exception as e:
            self._record_usage(
                input_tokens=total_usage["input_tokens"],
                output_tokens=total_usage["output_tokens"],
                tool_rounds=rounds_run,
                latency_ms=int((time.monotonic() - started) * 1000),
                success=False,
                error=str(e)[:500],
                sub_key=sub_key,
            )
            raise

        # Exhausted rounds — return whatever we have
        text = response.text or "" if response else ""  # type: ignore[possibly-undefined]
        self._record_usage(
            input_tokens=total_usage["input_tokens"],
            output_tokens=total_usage["output_tokens"],
            tool_rounds=rounds_run,
            latency_ms=int((time.monotonic() - started) * 1000),
            success=True,
            sub_key=sub_key,
        )
        return {"text": text, "parsed": None, "usage": total_usage}

    def _record_usage(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        tool_rounds: int = 1,
        latency_ms: int | None = None,
        retries: int = 0,
        success: bool = True,
        error: str | None = None,
        sub_key: str | None = None,
    ) -> None:
        """Best-effort ledger write. Never raises."""
        from pipeline.llm.usage_ledger import UsageEvent, record

        record(UsageEvent(
            panel=self._panel,
            provider="gemini",
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_rounds=tool_rounds,
            latency_ms=latency_ms,
            retries=retries,
            success=success,
            error=error,
            sub_key=sub_key,
        ))

    async def _rate_limit(self) -> None:
        """Enforce minimum interval between requests."""
        now = time.monotonic()
        elapsed = now - self._last_call
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
        self._last_call = time.monotonic()
