"""
Docker DevOps Agent — Interactive REPL Entry Point

Features:
- Rich CLI with colored panels, spinners, and formatted output
- Conversation memory persistence across sessions
- Structured logging of all interactions
- Graceful error handling and shutdown
"""

import os
import sys
import traceback

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(__file__))

from utils.logger import get_logger, log_exception, log_session_start
from utils.memory import ConversationMemory

agent_log = get_logger("agent")

# ── Rich imports ──────────────────────────────────────
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    from rich.spinner import Spinner
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.table import Table
    from rich import box
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

console = Console() if HAS_RICH else None


def print_banner():
    """Display the startup banner."""
    if HAS_RICH:
        banner_text = Text()
        banner_text.append("🐳 Docker DevOps Agent", style="bold cyan")
        banner_text.append("\n   Strands Agents SDK", style="dim")
        banner_text.append(" × ", style="dim")
        banner_text.append("Gemini", style="bold yellow")
        banner_text.append("\n   Production-grade infrastructure management", style="dim")

        console.print(Panel(
            banner_text,
            border_style="cyan",
            box=box.DOUBLE_EDGE,
            padding=(1, 2),
        ))
    else:
        print("━" * 60)
        print("  🐳 Docker DevOps Agent — Strands Agents SDK")
        print("  Powered by Gemini | Production-grade infrastructure mgmt")
        print("━" * 60)


def print_container_status():
    """Show running containers at startup."""
    import subprocess
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.Image}}"],
            capture_output=True, text=True, timeout=10, shell=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            if HAS_RICH:
                table = Table(
                    title="Running Containers",
                    box=box.ROUNDED,
                    border_style="green",
                    title_style="bold green",
                )
                table.add_column("Name", style="cyan")
                table.add_column("Status", style="green")
                table.add_column("Image", style="dim")
                for line in lines:
                    parts = line.split("\t")
                    if len(parts) >= 3:
                        table.add_row(parts[0], parts[1], parts[2])
                console.print(table)
            else:
                print("\n📦 Currently running containers:")
                for line in lines:
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        print(f"   {parts[0]} ({parts[1]})")
        else:
            msg = "No running containers detected."
            if HAS_RICH:
                console.print(f"  [dim]{msg}[/dim]")
            else:
                print(f"  {msg}")
    except Exception:
        pass


def print_session_context(memory: ConversationMemory):
    """Show previous session context if available."""
    if memory.history:
        count = len(memory.history)
        if HAS_RICH:
            console.print(
                f"  [dim]📋 Loaded {count} exchange(s) from previous session[/dim]"
            )
        else:
            print(f"  📋 Loaded {count} exchange(s) from previous session")


def print_help():
    """Show available commands."""
    if HAS_RICH:
        help_table = Table(box=box.SIMPLE, border_style="dim")
        help_table.add_column("Command", style="cyan bold")
        help_table.add_column("Description", style="dim")
        help_table.add_row("Any natural language", "Ask the agent to do anything")
        help_table.add_row("history", "Show conversation history")
        help_table.add_row("clear", "Clear conversation memory")
        help_table.add_row("help", "Show this help")
        help_table.add_row("exit / quit", "End session")
        console.print(Panel(help_table, title="Commands", border_style="dim"))
    else:
        print("  Commands: history | clear | help | exit/quit")
        print("  Or just type natural language to talk to the agent.")


def run_agent_with_spinner(agent, prompt: str) -> str:
    """Run the agent with a visual spinner."""
    if HAS_RICH:
        with Live(
            Panel(Text("  Thinking...", style="yellow"), border_style="yellow", box=box.ROUNDED),
            console=console,
            refresh_per_second=10,
            transient=True,
        ):
            result = agent(prompt)
        return str(result)
    else:
        print("  ⏳ Processing...")
        result = agent(prompt)
        return str(result)


def main():
    """Main interactive REPL loop."""
    # Initialize logging
    log_session_start()

    # Initialize conversation memory
    memory = ConversationMemory(max_history=20)

    # Display startup
    print_banner()
    print_container_status()
    print_session_context(memory)

    if HAS_RICH:
        console.print()
        console.print("  [dim]Type [bold cyan]help[/bold cyan] for commands, or ask anything.[/dim]")
        console.print()
    else:
        print("\n  Type 'help' for commands, or ask anything.\n")

    # Initialize agent
    try:
        if HAS_RICH:
            with Live(
                Panel(Text("  Initializing agent...", style="yellow"), border_style="yellow", box=box.ROUNDED),
                console=console,
                transient=True,
            ):
                from container_agent import create_agent
                agent = create_agent()
        else:
            print("  Initializing agent...")
            from container_agent import create_agent
            agent = create_agent()

        agent_log.info("Agent initialized successfully", extra={"component": "main"})

        if HAS_RICH:
            console.print("  [bold green]✓[/bold green] [dim]Agent ready. 20 tools loaded.[/dim]\n")
        else:
            print("  ✓ Agent ready. 20 tools loaded.\n")

    except Exception as e:
        error_msg = f"Failed to initialize agent: {e}"
        if HAS_RICH:
            console.print(f"  [bold red]✗ {error_msg}[/bold red]")
        else:
            print(f"  ✗ {error_msg}")
        log_exception("main", type(e).__name__, str(e), "agent_init", "Fatal", False)
        sys.exit(1)

    # Build context from memory
    context_summary = memory.get_context_summary()
    if context_summary != "No previous session history.":
        agent_log.info(f"Session context loaded:\n{context_summary}", extra={"component": "main"})

    # REPL loop
    prompt_style = "[bold cyan]DevOps Agent >[/bold cyan] " if HAS_RICH else "DevOps Agent > "

    while True:
        try:
            if HAS_RICH:
                user_input = console.input(prompt_style).strip()
            else:
                user_input = input("DevOps Agent > ").strip()

            if not user_input:
                continue

            # Built-in commands
            if user_input.lower() in ("exit", "quit"):
                memory.save()
                if HAS_RICH:
                    console.print("\n  [dim]✓ Session saved. Logs at ./logs/[/dim]")
                else:
                    print("\n  ✓ Session saved. Logs at ./logs/")
                break

            if user_input.lower() == "help":
                print_help()
                continue

            if user_input.lower() == "history":
                ctx = memory.get_context_summary()
                if HAS_RICH:
                    console.print(Panel(ctx, title="Session History", border_style="blue"))
                else:
                    print(ctx)
                continue

            if user_input.lower() == "clear":
                memory.clear()
                if HAS_RICH:
                    console.print("  [dim]✓ Conversation memory cleared.[/dim]")
                else:
                    print("  ✓ Conversation memory cleared.")
                continue

            # Log user request
            agent_log.info(f"User request: {user_input}", extra={"component": "main.request"})

            # Run the agent
            response = run_agent_with_spinner(agent, user_input)

            # Display response
            if HAS_RICH:
                console.print()
                # Try to render as markdown for better formatting
                try:
                    console.print(Markdown(response))
                except Exception:
                    console.print(response)
                console.print()
            else:
                print(f"\n{response}\n")

            # Log and save to memory
            agent_log.info(
                f"Agent response delivered ({len(response)} chars)",
                extra={"component": "main.response"},
            )
            memory.add_exchange(user_input, response[:300])

        except KeyboardInterrupt:
            memory.save()
            if HAS_RICH:
                console.print("\n\n  [dim]✓ Session interrupted. Logs saved to ./logs/[/dim]")
            else:
                print("\n\n  ✓ Session interrupted. Logs saved to ./logs/")
            break

        except Exception as e:
            error_msg = str(e)
            log_exception(
                component="main",
                exc_type=type(e).__name__,
                message=error_msg,
                input_data=user_input if 'user_input' in dir() else "unknown",
                response=f"Error during agent execution — continuing session",
                safe_state=True,
            )
            if HAS_RICH:
                console.print(f"  [red]⚠ Error: {error_msg[:100]}[/red]")
                console.print("  [dim]The error has been logged. You can continue using the agent.[/dim]")
            else:
                print(f"  ⚠ Error: {error_msg[:100]}")
                print("  The error has been logged. You can continue using the agent.")


if __name__ == "__main__":
    main()
