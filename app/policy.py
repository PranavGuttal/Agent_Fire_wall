"""Policy engine: per-agent tool allowlist + JSON-schema argument validation.

Policies are authored ahead of time in policies.json, keyed by agent *name*
(the human-chosen label passed at registration) rather than agent_id, since
policies need to exist before an agent is ever registered and agent_id is
only assigned at registration time.

Two independent gates, checked in order:
1. Is `tool_name` on this agent's allowlist at all?
2. Do `args` satisfy that tool's JSON schema (if one is defined)?
"""
import json
from pathlib import Path
from typing import Any

from jsonschema import ValidationError, validate

from app.db import get_conn

POLICY_PATH = Path(__file__).resolve().parent.parent / "policies.json"


class PolicyDecision:
    def __init__(self, allowed: bool, reason: str):
        self.allowed = allowed
        self.reason = reason


def _load_policies() -> dict:
    if not POLICY_PATH.exists():
        return {}
    return json.loads(POLICY_PATH.read_text())


def _agent_name(agent_id: str) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT name FROM agents WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        return row["name"] if row else None


def evaluate(agent_id: str, tool_name: str, args: dict[str, Any]) -> PolicyDecision:
    name = _agent_name(agent_id)
    if name is None:
        return PolicyDecision(False, "unknown agent")

    agent_policy = _load_policies().get(name)
    if agent_policy is None:
        return PolicyDecision(False, f"no policy defined for agent '{name}'")

    tool_policy = agent_policy.get("tools", {}).get(tool_name)
    if tool_policy is None:
        return PolicyDecision(False, f"'{name}' is not allowed to call '{tool_name}'")

    schema = tool_policy.get("schema")
    if schema:
        try:
            validate(instance=args, schema=schema)
        except ValidationError as e:
            return PolicyDecision(False, f"argument validation failed: {e.message}")

    return PolicyDecision(True, "allowed")
