# Agent Runtime Firewall — build plan

## Scope decision: go deep, not wide

You have 1-2 weeks and you're targeting AI/ML infra roles. In that time, a shallow version of all five features (identity, permission enforcement, arg validation, sequence detection, audit log) will read as a toy to anyone who pokes at it. A deep, correct version of three of them, with the other two scoped honestly as "designed, roadmapped, partially stubbed," reads as engineering judgment — which is exactly what an infra interviewer is screening for.

**Build deep:**
1. Per-agent identity (signed tokens, no shared credentials)
2. Permission enforcement (allowlist + argument schema validation) — this is the core value prop and the CVE hook
3. Tamper-evident audit log

**Build shallow but real (v1, extend later):**
4. Sequence/behavior monitoring — ship one concrete detector (e.g. "read then external send" within N calls), not a generic ML anomaly system
5. OpenTelemetry tracing — wire it through every call so the demo has a trace waterfall, even if you don't build custom dashboards

Cutting scope here is not a compromise, it's the plan. Recruiters and interviewers reward a system that does a few things correctly under load over one that does everything superficially.

## Architecture

Three layers:

- **Agent layer** — a LangGraph agent (or any MCP client) that wants to call tools.
- **Firewall middleware** — a FastAPI service the agent's tool calls are routed through. Internally: identity check → policy engine (allowlist lookup) → argument validator (JSON schema per tool) → sequence monitor (stateful, keyed by agent session) → dispatch to the real tool. Every stage writes to the audit log; every call gets an OpenTelemetry span.
- **Tool layer** — the actual file access, APIs, DB, email, etc. The firewall never touches tool logic, only decides whether to forward the call.

Key design choice: the firewall should be a **reverse proxy for MCP**, not a library each agent has to import correctly. If it's a library, a compromised or careless agent can just not call it. If it's a proxy that owns the only path to real tools, enforcement is structural, not optional. This is the single most important architectural decision — lead with it in interviews.

## Core data model

- `AgentIdentity`: agent_id, public key or signed JWT, issued_at, expiry
- `Policy`: agent_id → list of {tool_name, allowed_arg_schema}
- `ToolCallRequest`: agent_id, tool_name, args, session_id, timestamp
- `ToolCallDecision`: request, allowed (bool), reason, latency
- `AuditEntry`: append-only, hash-chained (each entry includes hash of previous entry) so tampering is detectable without a full blockchain

## 10-day plan

**Day 1-2 — skeleton and identity** ✅ done
FastAPI service. Each agent gets an Ed25519 keypair at registration (public key stored in SQLite). Every incoming call to a protected endpoint must present a valid signed identity — reject anything else. Verified: valid token accepted, missing token rejected, forged token rejected.

**Day 3-4 — policy engine + argument validation** ✅ done
Define policies as YAML or JSON: agent_id → allowed tools → JSON schema per tool's arguments. Validate both the tool name against the allowlist and the arguments against the schema before forwarding. Demo: an agent approved only for `read_file` gets blocked calling `send_email`; an agent approved for `read_file` but passing a path outside its allowed directory gets blocked by schema/arg validation.

**Day 5 — audit log**
Append-only log (SQLite is fine, or a flat file with hash chaining) recording every decision — allowed and denied — with agent_id, tool, args, decision, reason, timestamp, and hash of the previous entry. Add a small verification script that walks the chain and flags tampering. This is a strong, cheap "security" credential — build it solid.

**Day 6-7 — sequence monitor (v1)**
Keep per-session state (a rolling window of recent calls per agent). Implement one real rule: read-sensitive-file → external-send within K calls triggers a block + high-severity audit entry. Make the rule config-driven (a small DSL or even just a list of {trigger, follow, window} tuples) so you can say "this generalizes" without having actually generalized it yet.

**Day 8 — OpenTelemetry tracing**
Instrument the FastAPI middleware so every proxied call creates a span with agent_id, tool_name, decision, and latency, and forwards trace context if the downstream tool is itself instrumented. Export to a local Jaeger or console exporter — you don't need a hosted backend for the demo, just a real trace waterfall you can screenshot or show live.

**Day 9 — real MCP integration**
Wire this in front of an actual MCP server (filesystem or a simple custom one) and a real LangGraph agent, not synthetic requests. This is what separates "I built a demo" from "I built infrastructure." Even one real integration matters far more than more unit tests.

**Day 10 — README, docs, demo script**
Write the README to lead with the problem (the CVE stat, the "who's actually enforcing this" gap), show the architecture diagram, and include a 2-minute "try it yourself" (docker-compose up, run three canned requests: one allowed, one denied by policy, one denied by sequence detection).

## What to explicitly NOT build for v1

- A UI/dashboard (use logs + a script, not a frontend)
- Multi-tenant policy management UI
- ML-based anomaly detection — one hardcoded rule is more defensible than a half-working model
- Kubernetes/cloud deployment — Docker Compose is enough for a demo
- Support for every MCP transport — pick one (likely stdio or HTTP) and be explicit about the rest being future work

Naming these out loud in your README as "deliberately out of scope for v1" is itself a signal of engineering maturity.

## Presenting it to recruiters / interviewers

- Open with the gap, not the code: "40+ MCP/agent CVEs in the first four months of 2026, and even the platforms Microsoft/IBM/Boomi are building admit the identity + real-time enforcement layer is unsolved. I built that layer."
- Show, don't just describe: a live terminal demo of an agent getting blocked (wrong tool, bad args, bad sequence) beats any slide.
- Have the trace waterfall ready as a screenshot — it signals "this person thinks about observability," which matters a lot for AI/ML infra roles specifically.
- Be ready to talk about the proxy-vs-library decision above — it's the one architectural call that shows real judgment, not just feature-checking.
- Have a clear, one-sentence answer for "how is this different from what Microsoft/IBM are building": you're solving the narrow enforcement primitive, not the whole management platform — and that's why one engineer could ship it in two weeks.
