from pydantic import BaseModel


class RegisterAgentRequest(BaseModel):
    name: str


class RegisterAgentResponse(BaseModel):
    agent_id: str
    name: str
    private_key_pem: str
    warning: str = "Store this private key now. It is not saved server-side and will not be shown again."


class WhoAmIResponse(BaseModel):
    agent_id: str


class ToolCallRequest(BaseModel):
    args: dict = {}


class ToolCallResponse(BaseModel):
    tool_name: str
    decision: str  # "allowed" | "denied"
    reason: str
    result: dict | None = None
