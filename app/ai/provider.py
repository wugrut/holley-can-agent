"""
Provider-agnostic LLM interface for reasoning and natural language interpretation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@dataclass
class ToolCall:
    name: str
    arguments: Dict[str, Any]
    call_id: str = "call_001"


@dataclass
class LLMResponse:
    content: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    model_name: str = "provider_agnostic"
    tokens_used: int = 0


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for pluggable LLM backends (Gemini, Claude, OpenAI, Local Ollama)."""

    async def generate_response(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        ...


class DeterministicMockLLMProvider(LLMProvider):
    """
    Deterministic mock provider for automated testing and offline development.
    Answers engine questions using strictly grounded rule synthesis.
    """

    async def generate_response(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        user_query = messages[-1]["content"].lower() if messages else ""

        # Check for tool call requests
        if "idle" in user_query and "surge" in user_query:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(name="query_diagnostics", arguments={"category": "idle"})],
            )
        elif "fuel" in user_query or "correction" in user_query:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(name="query_diagnostics", arguments={"category": "fueling"})],
            )
        elif "cam" in user_query or "modification" in user_query:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(name="get_modification_history", arguments={})],
            )

        # Default grounded response
        return LLMResponse(
            content=(
                "I am your EFI Intelligence Copilot. Based on your engine telemetry and diagnostics, "
                "I can analyze idle stability, fueling learn drift, operating baselines, and modification history."
            ),
            model_name="deterministic_mock",
        )
