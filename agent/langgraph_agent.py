"""Real LangGraph agent, driven by a real Groq LLM, whose tool calls are
routed through the firewall (POST /proxy/{tool_name}) rather than calling
MCP directly.

This is the point of the whole project: the agent never talks to the MCP
filesystem server itself. It only knows the firewall's HTTP API. Every
tool choice the model makes still passes through identity verification,
the policy engine, the sequence monitor, and the audit log, exactly like
every other agent in this project — enforcement is structural, not
something the agent has to cooperate with.

Setup:
    1. Start the firewall: uvicorn app.main:app --port 8000
       (and, for the real MCP dispatch, docker compose up -d isn't needed —
       the MCP filesystem server is a subprocess the firewall launches itself)
    2. Copy .env.example to .env and set a real GROQ_API_KEY
    3. python agent/langgraph_agent.py "list the files in your sandbox and read notes.txt"
"""
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langgraph.prebuilt import create_react_agent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.identity import sign_request  # noqa: E402

load_dotenv()

BASE_URL = "http://127.0.0.1:8000"
AGENT_NAME = "filesystem-agent"

DEFAULT_PROMPT = "List the files in your sandbox, then read notes.txt and summarize it."


def _register() -> dict:
    resp = httpx.post(f"{BASE_URL}/agents/register", json={"name": AGENT_NAME})
    resp.raise_for_status()
    return resp.json()


def _call_proxy(identity: dict, tool_name: str, args: dict) -> dict:
    """Every tool call funnels through here -> signed request -> /proxy.

    This is the only way this agent can reach a tool. There is no direct
    path to the MCP server from agent code.
    """
    token = sign_request(identity["agent_id"], identity["private_key_pem"])
    resp = httpx.post(
        f"{BASE_URL}/proxy/{tool_name}",
        headers={"Authorization": f"Bearer {token}"},
        json={"args": args},
    )
    if resp.status_code != 200:
        return {"error": resp.json().get("detail", resp.text)}
    return resp.json()["result"]


def build_agent(identity: dict):
    @tool
    def list_directory(path: str = ".") -> dict:
        """List files in the agent's sandboxed directory. path is relative to the sandbox root."""
        return _call_proxy(identity, "list_directory", {"path": path})

    @tool
    def read_file(path: str) -> dict:
        """Read a file's contents. path must be inside the sandbox, e.g. 'notes.txt'."""
        return _call_proxy(identity, "read_file", {"path": path})

    llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0)
    return create_react_agent(llm, tools=[list_directory, read_file])


def main() -> None:
    prompt = " ".join(sys.argv[1:]) or DEFAULT_PROMPT

    print(f"1. Registering '{AGENT_NAME}' with the firewall...")
    identity = _register()

    print(f"\n2. Running the LangGraph agent with prompt:\n   {prompt!r}\n")
    agent = build_agent(identity)
    result = agent.invoke({"messages": [{"role": "user", "content": prompt}]})

    print("3. Final answer:\n")
    print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
