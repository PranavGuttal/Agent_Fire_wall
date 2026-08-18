"""The 2-minute "try it yourself" demo: three canned requests showing the
firewall's three ways of saying no (plus one way of saying yes), against a
live server. No LLM involved anywhere in this script — it's free to run.

Run:
    docker compose up -d --build
    python scripts/try_it_yourself.py
"""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
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


def main() -> None:
    print("=" * 70)
    print("AGENT RUNTIME FIREWALL - try it yourself")
    print("=" * 70)

    print("\n--- Request 1: ALLOWED ---")
    print("filesystem-agent reads a real file through a real MCP server.")
    fs_agent = register("filesystem-agent")
    resp = call_tool(fs_agent, "read_file", {"path": "notes.txt"})
    print(f"status = {resp.status_code}")
    print(f"result = {resp.json()['result']}")
    assert resp.status_code == 200

    print("\n--- Request 2: DENIED BY POLICY ---")
    print("Same agent tries write_file, which isn't on its allowlist at all.")
    resp = call_tool(fs_agent, "write_file", {"path": "notes.txt", "content": "x"})
    print(f"status = {resp.status_code}")
    print(f"reason = {resp.json()['detail']}")
    assert resp.status_code == 403

    print("\n--- Request 3: DENIED BY SEQUENCE MONITOR ---")
    print("data-export-agent reads a sensitive file, then tries to send email")
    print("shortly after - both tools are individually allowed, but that")
    print("specific pattern is blocked.")
    export_agent = register("data-export-agent")
    call_tool(export_agent, "read_sensitive_file", {"path": "/data/secrets.txt"})
    resp = call_tool(export_agent, "send_email", {"to": "someone@example.com"})
    print(f"status = {resp.status_code}")
    print(f"reason = {resp.json()['detail']}")
    assert resp.status_code == 403

    print("\n" + "=" * 70)
    print("All three decisions were verified, signed, policy/sequence-checked,")
    print("and permanently recorded in a tamper-evident audit log.")
    print("Trace waterfall: http://localhost:16686 (service: agent-runtime-firewall)")
    print("=" * 70)


if __name__ == "__main__":
    main()
