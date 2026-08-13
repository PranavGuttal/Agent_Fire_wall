"""Tamper-evident audit log: every policy decision (allowed or denied) is
appended to a single global hash chain.

Each entry stores a hash of (its own fields + the previous entry's hash).
That means changing or deleting any row breaks every entry_hash after it,
so tampering is detectable by recomputing the chain and comparing —
verify_chain() below does exactly that.

This is a hash chain, not a blockchain: no consensus, no mining, just a
cheap, well-understood integrity check appropriate for a single append-only
log written by one service.
"""
import datetime
import hashlib

from app.db import get_conn

GENESIS_HASH = "0" * 64


def _compute_hash(
    prev_hash: str,
    agent_id: str,
    tool_name: str,
    decision: str,
    reason: str,
    severity: str,
    timestamp: str,
) -> str:
    payload = f"{prev_hash}|{agent_id}|{tool_name}|{decision}|{reason}|{severity}|{timestamp}"
    return hashlib.sha256(payload.encode()).hexdigest()


def _last_hash(conn) -> str:
    row = conn.execute(
        "SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row["entry_hash"] if row else GENESIS_HASH


def append_entry(
    agent_id: str, tool_name: str, decision: str, reason: str, severity: str = "normal"
) -> None:
    """Append one decision to the audit log, chained onto the previous entry."""
    timestamp = datetime.datetime.utcnow().isoformat()
    with get_conn() as conn:
        prev_hash = _last_hash(conn)
        entry_hash = _compute_hash(
            prev_hash, agent_id, tool_name, decision, reason, severity, timestamp
        )
        conn.execute(
            """
            INSERT INTO audit_log
                (agent_id, tool_name, decision, reason, severity, timestamp, prev_hash, entry_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (agent_id, tool_name, decision, reason, severity, timestamp, prev_hash, entry_hash),
        )
        conn.commit()


def verify_chain() -> tuple[bool, int | None]:
    """Walk the whole log in order and recompute each hash from its stored
    fields. Returns (True, None) if intact, or (False, id) for the first
    row whose recomputed hash doesn't match what's stored.
    """
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM audit_log ORDER BY id ASC").fetchall()

    expected_prev = GENESIS_HASH
    for row in rows:
        if row["prev_hash"] != expected_prev:
            return False, row["id"]
        recomputed = _compute_hash(
            row["prev_hash"],
            row["agent_id"],
            row["tool_name"],
            row["decision"],
            row["reason"],
            row["severity"],
            row["timestamp"],
        )
        if recomputed != row["entry_hash"]:
            return False, row["id"]
        expected_prev = row["entry_hash"]

    return True, None
