"""OpenAI-first structured gateway plus deterministic test client."""

from __future__ import annotations

import os
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel


ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMClient(Protocol):
    """Only structured completions are exposed to the research workflow."""

    model_name: str

    def complete(self, agent_name: str, prompt: str, output_type: type[ModelT], *, max_output_tokens: int | None = None) -> ModelT:
        """Return a schema-valid response without granting tools or credentials."""


class FakeLLMClient:
    """Deterministic client for tests and offline development."""

    model_name = "fake-structured-model"
    last_token_usage = 0
    last_cost_usd = 0.0

    def __init__(self, responses: dict[str, dict[str, Any]] | None = None) -> None:
        self.responses = responses or {}

    def complete(self, agent_name: str, prompt: str, output_type: type[ModelT], *, max_output_tokens: int | None = None) -> ModelT:
        payload = self.responses.get(
            agent_name,
            {
                "agent": agent_name,
                "asset": "UNKNOWN",
                "signal": "HOLD",
                "confidence": 0.0,
                "claims": [{"kind": "UNCERTAINTY", "statement": "No model response configured.", "data_sources": []}],
                "risks": ["offline_fake_client"],
            },
        )
        return output_type.model_validate(payload)


class OpenAIResearchClient:
    """Lazy OpenAI Responses client; only this module reads OPENAI_API_KEY."""

    def __init__(
        self,
        model_name: str = "gpt-5-mini",
        client: Any | None = None,
        *,
        timeout_seconds: float = 30.0,
        input_cost_per_million: float | None = None,
        output_cost_per_million: float | None = None,
    ) -> None:
        self.model_name = model_name
        self._client = client
        self.timeout_seconds = timeout_seconds
        self.input_cost_per_million = input_cost_per_million
        self.output_cost_per_million = output_cost_per_million
        self.last_token_usage = 0
        self.last_cost_usd = 0.0

    def complete(self, agent_name: str, prompt: str, output_type: type[ModelT], *, max_output_tokens: int | None = None) -> ModelT:
        if self._client is None:
            if not os.getenv("OPENAI_API_KEY"):
                raise RuntimeError("OPENAI_API_KEY is required to run research agents.")
            from openai import OpenAI

            self._client = OpenAI(timeout=self.timeout_seconds)
        response = self._client.responses.create(
            model=self.model_name,
            input=[
                {"role": "system", "content": "Return only JSON matching the supplied schema. Never invent market data."},
                {"role": "user", "content": prompt},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": output_type.__name__,
                    "schema": output_type.model_json_schema(),
                    "strict": True,
                }
            },
            timeout=self.timeout_seconds,
            max_output_tokens=max_output_tokens,
        )
        usage = getattr(response, "usage", None)
        self.last_token_usage = int(
            getattr(usage, "input_tokens", 0) + getattr(usage, "output_tokens", 0),
        )
        input_tokens = int(getattr(usage, "input_tokens", 0))
        output_tokens = int(getattr(usage, "output_tokens", 0))
        if self.input_cost_per_million is None or self.output_cost_per_million is None:
            self.last_cost_usd = 0.0
        else:
            self.last_cost_usd = (
                input_tokens * self.input_cost_per_million
                + output_tokens * self.output_cost_per_million
            ) / 1_000_000.0
        return output_type.model_validate_json(response.output_text)
