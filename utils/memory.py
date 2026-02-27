"""
Conversation memory module for the Docker DevOps Agent.

Provides session persistence — the agent remembers past interactions
including deployments, test results, and incidents across sessions.

Memory is stored as JSON files in ./logs/sessions/
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.logger import get_logger

agent_log = get_logger("agent")

SESSIONS_DIR = Path(__file__).parent.parent / "logs" / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


class ConversationMemory:
    """Manages conversation history persistence across agent sessions."""

    def __init__(self, max_history: int = 20):
        """
        Args:
            max_history: Maximum number of exchanges to keep in memory.
        """
        self.max_history = max_history
        self.history: list[dict] = []
        self.session_file = SESSIONS_DIR / "latest_session.json"
        self.load()

    def load(self):
        """Load the last session's conversation history."""
        if self.session_file.exists():
            try:
                with open(self.session_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.history = data.get("history", [])[-self.max_history:]
                agent_log.info(
                    f"Loaded {len(self.history)} exchanges from previous session",
                    extra={"component": "memory"},
                )
            except (json.JSONDecodeError, Exception) as e:
                agent_log.warning(
                    f"Could not load session history: {e}",
                    extra={"component": "memory"},
                )
                self.history = []

    def save(self):
        """Save current conversation history to disk."""
        ist = timezone(timedelta(hours=5, minutes=30))
        data = {
            "last_updated": datetime.now(ist).isoformat(),
            "exchange_count": len(self.history),
            "history": self.history[-self.max_history:],
        }
        try:
            with open(self.session_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            agent_log.warning(
                f"Could not save session history: {e}",
                extra={"component": "memory"},
            )

    def add_exchange(self, user_input: str, agent_response: str):
        """Record a user/agent exchange.

        Args:
            user_input: What the user asked.
            agent_response: Summary of what the agent did (not full response).
        """
        ist = timezone(timedelta(hours=5, minutes=30))
        self.history.append({
            "timestamp": datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S"),
            "user": user_input,
            "agent": agent_response[:500],  # Truncate to keep memory lean
        })
        # Auto-save after each exchange
        self.save()

    def get_context_summary(self) -> str:
        """Get a summary of recent conversation history for agent context.

        Returns:
            Formatted string of last N exchanges.
        """
        if not self.history:
            return "No previous session history."

        lines = [f"Previous session — {len(self.history)} exchanges:"]
        for ex in self.history[-5:]:  # Last 5 for context
            lines.append(f"  [{ex['timestamp']}] User: {ex['user'][:80]}")
            lines.append(f"                    Agent: {ex['agent'][:80]}")
        return "\n".join(lines)

    def clear(self):
        """Clear all conversation history."""
        self.history = []
        self.save()
        agent_log.info("Session history cleared", extra={"component": "memory"})
