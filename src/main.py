"""CLI entry point — run an interactive ReAct chat with the agent."""
from __future__ import annotations

import argparse
import asyncio
import sys

from rich.console import Console
from rich.panel import Panel

from src.agent.prompts import VALUATION_PROMPT
from src.agent.react_agent import ReActAgent
from src.config import settings
from src.mcp_client.manager import MCPManager
from src.providers.factory import build_provider


console = Console()


def _print_banner() -> None:
    mode = settings.mode.upper()
    model = (
        settings.perplexity_model if settings.mode == "online" else settings.ollama_model
    )
    backend = "Perplexity" if settings.mode == "online" else "Ollama"
    console.print(
        Panel.fit(
            f"[bold]AI Agent[/bold]\n"
            f"Mode:    [cyan]{mode}[/cyan]\n"
            f"Backend: [cyan]{backend}[/cyan]\n"
            f"Model:   [cyan]{model}[/cyan]\n\n"
            f"Type your message. Commands: [yellow]/reset[/yellow], "
            f"[yellow]/tools[/yellow], [yellow]/exit[/yellow]",
            border_style="blue",
        )
    )


async def main() -> int:
    parser = argparse.ArgumentParser(prog="ai-agent",
                                      description="ReAct AI agent with MCP tools")
    parser.add_argument("--valuation", metavar="COMPANY", default=None,
                         help="Run a DCF valuation for the given company "
                              "(name or ticker), then exit. Non-interactive.")
    parser.add_argument("--prompt", metavar="TEXT", default=None,
                         help="Run a single prompt non-interactively, then exit.")
    args = parser.parse_args()

    errors = settings.validate()
    if errors:
        for e in errors:
            console.print(f"[red]config error:[/red] {e}")
        return 1

    settings.workspace()  # ensure workspace dir exists
    provider = build_provider(settings)

    async with MCPManager(settings.mcp_config_path) as mcp:
        # If --valuation is set, replace the system prompt with VALUATION_PROMPT
        agent_kwargs = dict(
            provider=provider,
            mcp=mcp,
            max_iterations=max(settings.max_iterations, 30) if args.valuation
                            else settings.max_iterations,
            temperature=settings.temperature,
            verbose=settings.verbose,
            system_prompt_path=settings.system_prompt_path,
        )
        agent = ReActAgent(**agent_kwargs)

        if args.valuation:
            # override system prompt with the valuation workflow
            agent.system_prompt = VALUATION_PROMPT
            agent.messages[0] = {"role": "system", "content": VALUATION_PROMPT}

        _print_banner()
        console.print(
            f"[dim]Loaded {len(mcp.list_tool_names())} MCP tool(s) "
            f"from {len(mcp.sessions)} server(s).[/dim]\n"
        )

        # ---- non-interactive modes ------------------------------------
        if args.valuation:
            user_msg = (
                f"Build a complete DCF valuation for: {args.valuation}\n\n"
                f"Follow the 4-step workflow exactly. Source from filings, "
                f"flag estimates, and produce the .xlsx in the workspace."
            )
            console.print(f"[bold blue]you ›[/bold blue] {user_msg}\n")
            try:
                await agent.run(user_msg)
            except Exception as e:  # noqa: BLE001
                console.print(f"[red]agent error:[/red] {e}")
            return 0

        if args.prompt:
            console.print(f"[bold blue]you ›[/bold blue] {args.prompt}\n")
            try:
                await agent.run(args.prompt)
            except Exception as e:  # noqa: BLE001
                console.print(f"[red]agent error:[/red] {e}")
            return 0

        # ---- interactive REPL -----------------------------------------
        while True:
            try:
                user = console.input("[bold blue]you ›[/bold blue] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]bye[/dim]")
                return 0

            if not user:
                continue
            if user in {"/exit", "/quit", "exit", "quit"}:
                console.print("[dim]bye[/dim]")
                return 0
            if user == "/reset":
                agent.reset()
                console.print("[dim]conversation reset[/dim]\n")
                continue
            if user == "/tools":
                for name in mcp.list_tool_names():
                    console.print(f"  • {name}")
                console.print()
                continue

            try:
                await agent.run(user)
            except Exception as e:  # noqa: BLE001
                console.print(f"[red]agent error:[/red] {e}")
            console.print()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
