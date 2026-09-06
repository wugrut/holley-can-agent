"""
EngineCopilot orchestrating user dialogue, tool execution, and grounded AI responses.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.ai.prompts import COPILOT_SYSTEM_PROMPT
from app.ai.provider import LLMProvider, LLMResponse
from app.ai.tools import EngineCopilotToolRegistry


class EngineCopilot:
    """
    Conversational assistant for 'Ask Your Engine'.
    Executes tools on the deterministic registry and grounds all answers in empirical telemetry.
    """

    def __init__(
        self,
        provider: LLMProvider,
        tool_registry: EngineCopilotToolRegistry,
    ) -> None:
        self.provider = provider
        self.tools = tool_registry
        self.conversation_history: List[Dict[str, str]] = []

    async def ask(self, user_question: str) -> str:
        """Processes user question, dispatches necessary tools, and returns grounded explanation."""
        self.conversation_history.append({"role": "user", "content": user_question})

        # Step 1: Query LLM with available tools
        response: LLMResponse = await self.provider.generate_response(
            system_prompt=COPILOT_SYSTEM_PROMPT,
            messages=self.conversation_history,
        )

        # Step 2: Handle tool calls if returned
        if response.tool_calls:
            for call in response.tool_calls:
                tool_result = self.tools.execute_tool(call.name, call.arguments)
                self.conversation_history.append(
                    {"role": "assistant", "content": f"[Executed {call.name}]: {tool_result}"}
                )

            # Re-query LLM with tool results incorporated
            second_response: LLMResponse = await self.provider.generate_response(
                system_prompt=COPILOT_SYSTEM_PROMPT,
                messages=self.conversation_history,
            )
            final_text = second_response.content or response.content
            self.conversation_history.append({"role": "assistant", "content": final_text})
            return final_text

        final_text = response.content
        self.conversation_history.append({"role": "assistant", "content": final_text})
        return final_text
