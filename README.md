# Agent Runtime Firewall

Middleware that sits between an AI agent and the tools it calls, verifying identity, enforcing per-agent permissions, and logging every decision — the layer that's still missing between agents and the tools they're given access to.

Status: Day 6-7 of the build plan. Identity, policy enforcement (allowlist + argument validation), a tamper-evident audit log, and a sequence monitor are implemented and verified. Tracing and real MCP integration come next.

## What's here right now

- `app/identity.py` — each agent gets its own Ed25519 keypair at registration. No shared secrets. Agents sign a short-lived (60s) JWT per request with their private key; the server verifies it against the stored public key.
- `app/policy.py` — per-agent policy engine: checks a tool call against the agent's allowlist, then validates its arguments against a JSON schema (`policies.json`).
- `app/sequence.py` — sequence monitor: keeps a short rolling history of each agent's recent tool calls in memory and blocks a call if it completes a `{trigger, follow, window}` pattern from `sequence_rules.json` (v1 ships one rule: `read_sensitive_file` → `send_email` within 3 calls).
- `app/audit.py` — every allow/deny decision (from policy or sequence checks) is appended to a single hash chain (`audit_log` table): each entry hashes its own fields plus the previous entry's hash, so editing or deleting any row breaks every hash after it. Sequence violations are logged at `severity: "high"`. `verify_chain()` recomputes the chain and reports the first broken entry, if any.
- `app/main.py` — `/agents/register` to issue an identity, `/whoami` as a protected endpoint, `/proxy/{tool_name}` as the gated tool-call endpoint (identity → policy → arg validation → sequence check → audit log → stub dispatch).
- `scripts/demo_client.py` — registers an agent, proves a valid signed request is accepted, and proves a missing or forged token is rejected.
- `scripts/demo_policy.py` — registers two agents with different policies, proves an allowed call succeeds, a call with bad arguments is blocked, a call to a tool outside the agent's allowlist is blocked, and that all 4 decisions land in an intact audit chain.
- `scripts/demo_sequence.py` — proves `send_email` alone is fine, but `read_sensitive_file` followed by `send_email` within the window is blocked even though both tools are individually allowed — and that the denial is logged at high severity.
- `scripts/verify_audit.py` — walks the audit log's hash chain standalone (no server needed). `--tamper` corrupts a scratch copy of the DB first, to prove the verifier actually catches tampering rather than always reporting "intact".

## Setup (VS Code)

1. Open this folder in VS Code (`File > Open Folder`).
2. Open a terminal in VS Code (`` Ctrl+` ``) and create a virtual environment:
   ```
   python -m venv .venv
   ```
3. Activate it:
   - Windows: `.venv\Scripts\activate`
   - macOS/Linux: `source .venv/bin/activate`
4. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
5. In VS Code, select this `.venv` as your Python interpreter: `Ctrl+Shift+P` -> "Python: Select Interpreter" -> pick the one in `.venv`.

## Run it

Terminal 1 — start the server:
```
uvicorn app.main:app --reload --port 8000
```
Visit `http://127.0.0.1:8000/docs` for the interactive API (Swagger UI).

Terminal 2 — run the demos:
```
python scripts/demo_client.py
python scripts/demo_policy.py
python scripts/demo_sequence.py
python scripts/verify_audit.py
python scripts/verify_audit.py --tamper
```

`demo_client.py`: agent registration succeeds, a validly signed request is accepted (200), a request with no token is rejected, and a request forged with the wrong key is rejected (401) even though it claims the real agent's ID.

`demo_policy.py`: an agent allowed to call `delete_file` only within `/tmp/cache/` succeeds there (200) and is blocked outside it (403); an agent not allowed to call `delete_file` at all is blocked (403) even with valid arguments; and all 4 decisions are confirmed present in an intact audit chain.

`demo_sequence.py`: `send_email` on its own is allowed (200); after `read_sensitive_file`, a `send_email` within the configured window is blocked (403) even though both tools are individually on the agent's allowlist; and the denial is confirmed in the audit log at `severity: "high"`.

`verify_audit.py`: confirms the real audit log's hash chain is intact. `--tamper` corrupts one row in a scratch copy of the DB and shows the verifier catches it, pinpointing the exact entry where the chain breaks.

## Why this design

The server never stores or sees an agent's private key — only its public key, generated once at registration. Each request is a fresh, short-lived signature, not a long-lived shared token. That's what "verifiable identity" means here: possession of the private key is proof, not a bearer secret that could leak or be reused elsewhere.

## Next up (see build-plan.md)

- Day 8: OpenTelemetry spans across agent -> middleware -> tool.
- Day 9: wire it in front of a real MCP server and LangGraph agent — a real integration, not synthetic requests.
- Day 10: README/docs pass leading with the problem, an architecture diagram, and a 2-minute "try it yourself" demo (docker-compose up, three canned requests: allowed, denied by policy, denied by sequence detection).
