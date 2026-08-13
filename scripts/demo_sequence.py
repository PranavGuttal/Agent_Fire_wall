"""Demo: prove the sequence monitor blocks a read-then-external-send
pattern even though both individual calls are allowed on their own by the
agent's policy (see sequence_rules.json).

Run the server first (see README), then:
    python scripts/demo_sequence.py
"""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.db import get_conn  # noqa: E402
from app.identity import sign_request  # noqa: E402

BASE_URL = "http://127.0.0.1:8000"


def register(name: str) -> dict:
    resp = httpx.post(f"{BASE_URL}/agents/register", json={"name": name})
    resp.raise_for_status()
    return resp.json()


def call_tool(agent: dict, tool_name: str, args: dict) -> httpx.Response:
    token = sign_request(agent["agent_id"], agent["private_key_pem"])
    return httpx.post(
        f"{BASE_URL}/proxy/{tool_name}",
        headers={"Authorization": f"Bearer {token}"},
        json={"args": args},
    )


def last_audit_entry(agent_id: str) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM audit_log WHERE agent_id = ? ORDER BY id DESC LIMIT 1",
            (agent_id,),
        ).fetchone()
        return dict(row)


def main() -> None:
    print("1. Registering 'data-export-agent'...")
    agent = register("data-export-agent")

    print("\n2. send_email with NO prior read_sensitive_file call...")
    resp = call_tool(agent, "send_email", {"to": "someone@example.com"})
    print(f"   status = {resp.status_code}, body = {resp.json()}")
    assert resp.status_code == 200

    print("\n3. read_sensitive_file (allowed on its own)...")
    resp = call_tool(agent, "read_sensitive_file", {"path": "/data/secrets.txt"})
    print(f"   status = {resp.status_code}, body = {resp.json()}")
    assert resp.status_code == 200

    print("\n4. send_email again, now within the window after read_sensitive_file...")
    resp = call_tool(agent, "send_email", {"to": "someone@example.com"})
    print(f"   status = {resp.status_code}, body = {resp.json()}")
    assert resp.status_code == 403

    print("\n5. Checking the audit log recorded this as a HIGH severity denial...")
    entry = last_audit_entry(agent["agent_id"])
    print(
        f"   decision={entry['decision']}, severity={entry['severity']}, "
        f"reason={entry['reason']}"
    )
    assert entry["decision"] == "denied"
    assert entry["severity"] == "high"

    print("\nAll checks passed: read-then-send pattern blocked, even though both")
    print("individual tools are on this agent's allowlist.")


if __name__ == "__main__":
    main()
