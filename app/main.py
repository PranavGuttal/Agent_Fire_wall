from fastapi import Depends, FastAPI, HTTPException

from app.db import init_db
from app.identity import RegisteredAgent, register_agent, require_agent
from app.policy import evaluate
from app.schemas import (
    RegisterAgentResponse,
    RegisterAgentRequest,
    ToolCallRequest,
    ToolCallResponse,
    WhoAmIResponse,
)

app = FastAPI(title="Agent Runtime Firewall", version="0.1.0")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


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
def proxy(
    tool_name: str, req: ToolCallRequest, agent_id: str = Depends(require_agent)
) -> ToolCallResponse:
    """Gate a tool call behind identity + per-agent policy + argument validation.

    Dispatch is stubbed for now: real MCP/tool wiring is day 9 of the build
    plan. This endpoint's job is the allow/deny decision, not execution.
    """
    decision = evaluate(agent_id, tool_name, req.args)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)
    return ToolCallResponse(
        tool_name=tool_name,
        decision="allowed",
        reason=decision.reason,
        result={"stub": True, "tool": tool_name, "args": req.args},
    )
