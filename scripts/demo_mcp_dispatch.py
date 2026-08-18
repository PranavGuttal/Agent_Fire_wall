"""Demo: prove /proxy dispatches to a REAL MCP server, not a stub.

Registers 'filesystem-agent' (see policies.json), then:
  - list_directory  -> real directory listing from mcp_sandbox/ (via MCP)
  - read_file       -> real file contents from mcp_sandbox/notes.txt (via MCP)
  - read_file outside mcp_sandbox/ -> blocked by OUR policy schema, before
    the MCP server is ever called
  - write_file      -> blocked because filesystem-agent's policy doesn't
    allow it at all (proves enforcement holds on a real, capable tool)

Run the server first (see README) with Jaeger up if you want the trace
too, then:
    python scripts/demo_mcp_dispatch.py
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
    print("1. Registering 'filesystem-agent'...")
    agent = register("filesystem-agent")

    print("\n2. list_directory on the real sandbox...")
    resp = call_tool(agent, "list_directory", {"path": "."})
    print(f"   status = {resp.status_code}")
    print(f"   result = {resp.json()['result']}")
    assert resp.status_code == 200
    assert resp.json()["result"].get("stub") is not True, "expected a REAL result, got a stub"

    print("\n3. read_file on notes.txt inside the sandbox...")
    resp = call_tool(agent, "read_file", {"path": "notes.txt"})
    print(f"   status = {resp.status_code}")
    print(f"   result = {resp.json()['result']}")
    assert resp.status_code == 200
    assert "tamper-evident audit chain" in resp.json()["result"]["text"]

    print("\n4. read_file on a path outside mcp_sandbox/ (blocked by OUR policy)...")
    resp = call_tool(agent, "read_file", {"path": "/etc/passwd"})
    print(f"   status = {resp.status_code}, body = {resp.json()}")
    assert resp.status_code == 403

    print("\n5. write_file (not on filesystem-agent's allowlist at all)...")
    resp = call_tool(agent, "write_file", {"path": "notes.txt", "content": "overwritten"})
    print(f"   status = {resp.status_code}, body = {resp.json()}")
    assert resp.status_code == 403

    print("\nAll checks passed: /proxy dispatched real tool calls to a real MCP")
    print("server, and policy still blocked what it should - enforcement is real,")
    print("not just simulated against a stub.")


if __name__ == "__main__":
    main()
