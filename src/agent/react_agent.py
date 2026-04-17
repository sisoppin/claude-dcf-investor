"""ReAct-style agent loop using native tool/function calling."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel

from src.agent.prompts import DEFAULT_SYSTEM_PROMPT
from src.mcp_client.manager import MCPManager
from src.providers.base import LLMProvider


class ReActAgent:
    def __init__(
        self,
        provider: LLMProvider,
        mcp: MCPManager,
        max_iterations: int = 10,
        temperature: float = 0.3,
        verbose: bool = True,
        system_prompt_path: str = "",
    ) -> None:
        self.provider = provider
        self.mcp = mcp
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.verbose = verbose
        self.console = Console()

        self.system_prompt = self._load_system_prompt(system_prompt_path)
        self.messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt}
        ]

    @staticmethod
    def _load_system_prompt(path: str) -> str:
        if not path:
            return DEFAULT_SYSTEM_PROMPT
        p = Path(path)
        if not p.exists():
            return DEFAULT_SYSTEM_PROMPT
        return p.read_text(encoding="utf-8")

    # -------------------------------------------------------------------

    def _log_thought(self, text: str) -> None:
        if self.verbose and text:
            self.console.print(Panel(text, title="🧠 Thought", border_style="cyan"))

    def _log_action(self, name: str, args: dict[str, Any]) -> None:
        if self.verbose:
            try:
                pretty = json.dumps(args, indent=2, ensure_ascii=False)
            except (TypeError, ValueError):
                pretty = str(args)
            self.console.print(
                Panel(
                    f"[bold]{name}[/bold]\n{pretty}",
                    title="🛠  Action",
                    border_style="yellow",
                )
            )

    def _log_observation(self, result: str) -> None:
        if self.verbose:
            display = result if len(result) <= 1500 else result[:1500] + "\n…[truncated]"
            self.console.print(
                Panel(display, title="👀 Observation", border_style="green")
            )

    def _log_final(self, text: str) -> None:
        self.console.print(Panel(text, title="✅ Final Answer", border_style="magenta"))

    # -------------------------------------------------------------------

    async def run(self, user_input: str) -> str:
        """Run the ReAct loop for a single user turn. Returns the final answer."""
        self.messages.append({"role": "user", "content": user_input})
        tools = self.mcp.openai_tools()

        for step in range(1, self.max_iterations + 1):
            if self.verbose:
                self.console.rule(f"[dim]step {step}/{self.max_iterations}[/dim]")

            response = await self.provider.chat(
                messages=self.messages,
                tools=tools,
                temperature=self.temperature,
            )

            content = response.get("content") or ""
            tool_calls = response.get("tool_calls") or []

            # Show the model's reasoning (the "Thought") if any
            self._log_thought(content)

            if not tool_calls:
                # No more actions — this is the final answer
                self.messages.append({"role": "assistant", "content": content})
                self._log_final(content or "(empty response)")
                return content

            # Record the assistant turn that requested tools
            self.messages.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["arguments"]),
                            },
                        }
                        for tc in tool_calls
                    ],
                }
            )

            # Execute each tool and append its result
            for tc in tool_calls:
                self._log_action(tc["name"], tc["arguments"])
                result = await self.mcp.call_tool(tc["name"], tc["arguments"])
                self._log_observation(result)
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    }
                )

        msg = (
            f"Reached max_iterations ({self.max_iterations}) without a final answer. "
            "Increase MAX_ITERATIONS or simplify the task."
        )
        self._log_final(msg)
        return msg

    def reset(self) -> None:
        self.messages = [{"role": "system", "content": self.system_prompt}]
