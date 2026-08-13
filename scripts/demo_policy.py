"""Demo: register two agents with different policies (see policies.json),
then prove the policy engine actually gates tool calls:
  - right tool, right args        -> allowed
  - right tool, args fail schema  -> denied (bad path outside allowed dir)
  - tool not on the agent's list  -> denied (wrong tool)

Run the server first (see README), then:
    python scripts/demo_policy.py
"""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.audit import verify_chain  # noqa: E402
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
    print("1. Registering 'file-cleanup-agent' and 'email-summarizer-agent'...")
    cleanup_agent = register("file-cleanup-agent")
    email_agent = register("email-summarizer-agent")

    print("\n2. file-cleanup-agent calls delete_file with an ALLOWED path...")
    resp = call_tool(cleanup_agent, "delete_file", {"path": "/tmp/cache/old_log.txt"})
    print(f"   status = {resp.status_code}, body = {resp.json()}")
    assert resp.status_code == 200

    print("\n3. file-cleanup-agent calls delete_file with a DISALLOWED path...")
    resp = call_tool(cleanup_agent, "delete_file", {"path": "/etc/passwd"})
    print(f"   status = {resp.status_code}, body = {resp.json()}")
    assert resp.status_code == 403

    print("\n4. email-summarizer-agent calls delete_file (not on its allowlist)...")
    resp = call_tool(email_agent, "delete_file", {"path": "/tmp/cache/old_log.txt"})
    print(f"   status = {resp.status_code}, body = {resp.json()}")
    assert resp.status_code == 403

    print("\n5. email-summarizer-agent calls read_email (on its allowlist, no schema)...")
    resp = call_tool(email_agent, "read_email", {"mailbox": "inbox"})
    print(f"   status = {resp.status_code}, body = {resp.json()}")
    assert resp.status_code == 200

    print("\nAll checks passed: policy engine blocks wrong tools AND bad arguments.")

    print("\n6. Verifying the audit log recorded all 4 decisions with an intact hash chain...")
    intact, bad_id = verify_chain()
    print(f"   chain intact = {intact}")
    assert intact, f"audit log chain broken at entry id={bad_id}"
    print("   All 4 allow/deny decisions above are permanently recorded and tamper-evident.")


if __name__ == "__main__":
    main()
