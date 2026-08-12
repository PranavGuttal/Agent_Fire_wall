"""Agent identity: registration and per-request signature verification.

Design: each agent gets its own Ed25519 keypair at registration. The server
only ever stores the *public* key. The agent signs a short-lived JWT with its
*private* key and sends it as a bearer token on every call. The server
verifies the signature against the stored public key.

This means there is no shared secret between agents, and a leaked token is
useless after ~60 seconds because it's short-lived and re-signed per call.
"""
import datetime
import uuid

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import Depends, Header, HTTPException, status

from app.db import get_conn

TOKEN_TTL_SECONDS = 60


class RegisteredAgent:
    def __init__(self, agent_id: str, name: str, private_key_pem: str):
        self.agent_id = agent_id
        self.name = name
        self.private_key_pem = private_key_pem  # returned once, never stored server-side


def register_agent(name: str) -> RegisteredAgent:
    """Issue a new agent identity. Private key is shown once and not persisted."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    agent_id = str(uuid.uuid4())

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO agents (agent_id, name, public_key_pem, created_at) VALUES (?, ?, ?, ?)",
            (agent_id, name, public_pem, datetime.datetime.utcnow().isoformat()),
        )
        conn.commit()

    return RegisteredAgent(agent_id=agent_id, name=name, private_key_pem=private_pem)


def sign_request(agent_id: str, private_key_pem: str) -> str:
    """Client-side helper: sign a short-lived JWT proving control of the private key."""
    now = datetime.datetime.utcnow()
    payload = {
        "agent_id": agent_id,
        "iat": now,
        "exp": now + datetime.timedelta(seconds=TOKEN_TTL_SECONDS),
    }
    return jwt.encode(payload, private_key_pem, algorithm="EdDSA")


def _get_public_key(agent_id: str) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT public_key_pem FROM agents WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        return row["public_key_pem"] if row else None


def verify_token(token: str) -> str:
    """Verify a bearer token's signature against the claimed agent's stored public key.

    Returns the verified agent_id, or raises HTTPException(401).
    """
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
    except jwt.DecodeError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="malformed token")

    agent_id = unverified.get("agent_id")
    if not agent_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing agent_id claim")

    public_key_pem = _get_public_key(agent_id)
    if not public_key_pem:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown agent")

    try:
        jwt.decode(token, public_key_pem, algorithms=["EdDSA"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token expired")
    except jwt.InvalidSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid signature")
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token verification failed")

    return agent_id


def require_agent(authorization: str = Header(...)) -> str:
    """FastAPI dependency: extracts + verifies the bearer token, returns agent_id."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="expected Bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    return verify_token(token)
