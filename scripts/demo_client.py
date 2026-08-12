"""Demo: register an agent, sign a request with its private key, call a
protected endpoint, and prove that an unsigned/forged request gets rejected.

Run the server first (see README), then:
    python scripts/demo_client.py
"""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.identity import sign_request  # noqa: E402

BASE_URL = "http://127.0.0.1:8000"


def main() -> None:
    print("1. Registering agent 'demo-agent'...")
    resp = httpx.post(f"{BASE_URL}/agents/register", json={"name": "demo-agent"})
    resp.raise_for_status()
    agent = resp.json()
    print(f"   agent_id = {agent['agent_id']}")

    print("\n2. Calling /whoami with a valid signed token...")
    token = sign_request(agent["agent_id"], agent["private_key_pem"])
    resp = httpx.get(f"{BASE_URL}/whoami", headers={"Authorization": f"Bearer {token}"})
    print(f"   status = {resp.status_code}, body = {resp.json()}")
    assert resp.status_code == 200

    print("\n3. Calling /whoami with NO token...")
    resp = httpx.get(f"{BASE_URL}/whoami")
    print(f"   status = {resp.status_code}, body = {resp.json()}")
    assert resp.status_code in (401, 422)

    print("\n4. Calling /whoami with a token signed by a DIFFERENT (unregistered) key...")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    fake_key = Ed25519PrivateKey.generate().private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    forged_token = sign_request(agent["agent_id"], fake_key)  # claims the real agent_id, wrong key
    resp = httpx.get(f"{BASE_URL}/whoami", headers={"Authorization": f"Bearer {forged_token}"})
    print(f"   status = {resp.status_code}, body = {resp.json()}")
    assert resp.status_code == 401

    print("\nAll checks passed: identity is verified, not just claimed.")


if __name__ == "__main__":
    main()
