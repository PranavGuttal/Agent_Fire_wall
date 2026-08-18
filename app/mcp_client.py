"""Persistent client for the real MCP filesystem server.

Launches `npx -y @modelcontextprotocol/server-filesystem <sandbox_dir>` as a
subprocess over stdio and keeps one long-lived session open for the life of
the FastAPI app (see the lifespan handler in app/main.py).

If startup fails (no Node/npx, no internet for the first npx download,
etc.) the caller is expected to catch the exception and continue with
dispatch falling back to the stub path — real MCP is important, but
optional infrastructure: the identity/policy/sequence/audit pipeline must
keep working even without it.
"""
import logging
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

SANDBOX_DIR = Path(__file__).resolve().parent.parent / "mcp_sandbox"

# The subset of the filesystem server's real tool names this project fronts.
MCP_TOOL_NAMES = {"list_directory", "read_file", "write_file"}


class MCPClient:
    def __init__(self) -> None:
        self._stack: AsyncExitStack | None = None
        self.session: ClientSession | None = None

    async def start(self) -> None:
        self._stack = AsyncExitStack()
        server_params = StdioServerParameters(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", str(SANDBOX_DIR)],
        )
        read, write = await self._stack.enter_async_context(stdio_client(server_params))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        logger.info("MCP filesystem server ready, sandboxed to %s", SANDBOX_DIR)

    async def stop(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self.session = None

    async def call_tool(self, tool_name: str, args: dict[str, Any]) -> dict:
        if self.session is None:
            raise RuntimeError("MCP session is not active")
        result = await self.session.call_tool(tool_name, arguments=args)
        text_parts = [
            block.text for block in result.content if getattr(block, "type", None) == "text"
        ]
        return {"text": "\n".join(text_parts), "is_error": bool(result.is_error)}
