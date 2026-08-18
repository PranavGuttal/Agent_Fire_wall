import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException

from app.audit import append_entry
from app.db import init_db
from app.identity import RegisteredAgent, register_agent, require_agent
from app.mcp_client import MCP_TOOL_NAMES, MCPClient
from app.policy import evaluate
from app.sequence import check as check_sequence
from app.schemas import (
    RegisterAgentResponse,
    RegisterAgentRequest,
    ToolCallRequest,
    ToolCallResponse,
    WhoAmIResponse,
)
from app.tracing import get_tracer, setup_tracing

logger = logging.getLogger(__name__)
tracer = get_tracer()
mcp_client = MCPClient()

# --- Debug logging: uncomment these 4 lines to write every debug.log line
# below to ./debug.log (created in the project root). Comment back out to
# go quiet again. Nothing else in this file needs to change either way.
# _debug_file_handler = logging.FileHandler("debug.log")
# _debug_file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
# logger.addHandler(_debug_file_handler)
# logger.setLevel(logging.DEBUG)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_tracing()
    init_db()
    try:
        await mcp_client.start()
        logger.debug("MCP filesystem server started OK")
    except Exception:
        logger.warning(
            "MCP filesystem server unavailable; dispatch falls back to stub for "
            "MCP-backed tools.",
            exc_info=True,
        )
    yield
    await mcp_client.stop()


app = FastAPI(title="Agent Runtime Firewall", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/agents/register", response_model=RegisterAgentResponse)
def register(req: RegisterAgentRequest) -> RegisterAgentResponse:
    """Issue a new agent identity. Called once per agent, out of band from tool calls."""
    agent: RegisteredAgent = register_agent(req.name)
    return RegisterAgentResponse(
        agent_id=agent.agent_id,
        name=agent.name,
        private_key_pem=agent.private_key_pem,
    )


@app.get("/whoami", response_model=WhoAmIResponse)
def whoami(agent_id: str = Depends(require_agent)) -> WhoAmIResponse:
    """Protected endpoint: proves the caller holds a valid, verifiable agent identity."""
    return WhoAmIResponse(agent_id=agent_id)


@app.post("/proxy/{tool_name}", response_model=ToolCallResponse)
async def proxy(
    tool_name: str, req: ToolCallRequest, agent_id: str = Depends(require_agent)
) -> ToolCallResponse:
    """Gate a tool call behind identity + policy + argument validation + sequence checks.

    Dispatch is real for MCP-backed tools (see app/mcp_client.py) when the
    MCP filesystem server is available, and falls back to a stub for every
    other tool — keeping the earlier demo scripts unchanged.

    Every stage below runs inside its own span, nested under one parent
    span for the whole call, so a single trace shows exactly where time
    went and which stage produced the decision.
    """
    with tracer.start_as_current_span("proxy_tool_call") as parent_span:
        parent_span.set_attribute("agent_id", agent_id)
        parent_span.set_attribute("tool_name", tool_name)
        logger.debug("proxy called: tool=%s agent_id=%s args=%s", tool_name, agent_id, req.args)

        with tracer.start_as_current_span("policy.evaluate") as span:
            policy_decision = evaluate(agent_id, tool_name, req.args)
            span.set_attribute("allowed", policy_decision.allowed)
            logger.debug(
                "policy.evaluate -> allowed=%s reason=%r",
                policy_decision.allowed,
                policy_decision.reason,
            )
        if not policy_decision.allowed:
            parent_span.set_attribute("decision", "denied")
            with tracer.start_as_current_span("audit.append_entry"):
                append_entry(
                    agent_id=agent_id,
                    tool_name=tool_name,
                    decision="denied",
                    reason=policy_decision.reason,
                    severity="normal",
                )
            logger.debug("DENIED by policy: %r", policy_decision.reason)
            raise HTTPException(status_code=403, detail=policy_decision.reason)

        with tracer.start_as_current_span("sequence.check") as span:
            sequence_decision = check_sequence(agent_id, tool_name)
            span.set_attribute("blocked", sequence_decision.blocked)
            logger.debug(
                "sequence.check -> blocked=%s reason=%r",
                sequence_decision.blocked,
                sequence_decision.reason,
            )
        if sequence_decision.blocked:
            parent_span.set_attribute("decision", "denied")
            with tracer.start_as_current_span("audit.append_entry"):
                append_entry(
                    agent_id=agent_id,
                    tool_name=tool_name,
                    decision="denied",
                    reason=sequence_decision.reason,
                    severity="high",
                )
            logger.debug("DENIED by sequence monitor: %r", sequence_decision.reason)
            raise HTTPException(status_code=403, detail=sequence_decision.reason)

        parent_span.set_attribute("decision", "allowed")
        with tracer.start_as_current_span("audit.append_entry"):
            append_entry(
                agent_id=agent_id,
                tool_name=tool_name,
                decision="allowed",
                reason=policy_decision.reason,
                severity="normal",
            )

        with tracer.start_as_current_span("dispatch") as span:
            if tool_name in MCP_TOOL_NAMES and mcp_client.session is not None:
                backend = "mcp"
                result = await mcp_client.call_tool(tool_name, req.args)
            else:
                backend = "stub"
                result = {"stub": True, "tool": tool_name, "args": req.args}
            span.set_attribute("backend", backend)
            logger.debug("dispatch -> backend=%s result=%s", backend, result)

        return ToolCallResponse(
            tool_name=tool_name,
            decision="allowed",
            reason=policy_decision.reason,
            result=result,
        )
