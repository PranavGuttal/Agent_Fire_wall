"""Sequence monitor (v1): flags one concrete call pattern rather than a
generic anomaly detector.

Keeps a short rolling history of each agent's recent tool calls in memory
(keyed by agent_id — no session concept yet, see build-plan.md). Rules are
config-driven: a list of {trigger, follow, window} in sequence_rules.json.
A call is blocked if `trigger` appears anywhere in that agent's last
`window` calls and the current call is `follow`.

In-memory and per-process by design for v1: state doesn't need to survive
a restart yet, and there's a single server process in this deployment.
"""
import json
from collections import defaultdict
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parent.parent / "sequence_rules.json"
MAX_HISTORY = 50

_history: dict[str, list[str]] = defaultdict(list)


class SequenceDecision:
    def __init__(self, blocked: bool, reason: str):
        self.blocked = blocked
        self.reason = reason


def _load_rules() -> list[dict]:
    if not RULES_PATH.exists():
        return []
    return json.loads(RULES_PATH.read_text())


def check(agent_id: str, tool_name: str) -> SequenceDecision:
    """Check tool_name against this agent's recent history, then record
    this call into that history for future checks.
    """
    history = _history[agent_id]
    decision = SequenceDecision(False, "no sequence violation")

    for rule in _load_rules():
        if rule["follow"] != tool_name:
            continue
        window = rule["window"]
        recent = history[-window:] if window > 0 else []
        if rule["trigger"] in recent:
            decision = SequenceDecision(
                True,
                f"sequence violation: '{rule['trigger']}' followed by "
                f"'{tool_name}' within {window} calls",
            )
            break

    history.append(tool_name)
    del history[:-MAX_HISTORY]
    return decision


def reset() -> None:
    """Test/demo helper: clear all in-memory history."""
    _history.clear()
