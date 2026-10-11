"""mcp_server.py — our support tools behind an MCP server (exam task 2.4).

What this file does:
  - Offers every tool in tools.py to any MCP client (our agent later, Claude Code, the Inspector).
  - Runs each call through the SAME pipeline the agent uses today: the hooks (refund limit,
    auto-escalation) and the verification gate. The rules live HERE, so they hold no matter
    which client connects.

Two things to know:
  - Tool definitions are NOT rewritten. The server reads tools.py, so there is one place to edit them.
  - stdio: the client starts this file as a program and the two talk through its standard input
    and output. That channel carries the protocol messages, so nothing else may print to stdout.
    (Our fake verification message goes to stderr for this reason.)

Without SESSION_ID, one server process = one conversation (a new process begins unverified).
With SESSION_ID (set by the client), the session is stored in .sessions/ and shared across processes.
Run it:  .venv/bin/python mcp_server.py
"""

import os

import anyio
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

import session_store
from hooks import call_tool
from tool_runner import new_session
from tools import TOOLS

# Two ways to hold the conversation's session:
#   SESSION_ID set  -> loaded from and saved to .sessions/ on every call, so it survives new server
#                      processes (the Agent SDK client starts one per turn) and agent handoffs.
#   not set         -> kept in memory for this one process (the Inspector, quick tests).
SESSION_ID = os.environ.get("SESSION_ID")
SESSION = new_session()


async def list_tools(context, params):
    # Claude (through the client) learns what exists from this list. Same names, descriptions
    # and input schemas we already wrote and reviewed in tools.py.
    return types.ListToolsResult(
        tools=[
            types.Tool(name=t["name"], description=t["description"], input_schema=t["input_schema"])
            for t in TOOLS
        ]
    )


async def handle_call(context, params):
    # agent_name=None: this server cannot tell which agent is asking, so the per-agent scope check
    # is skipped here. The client enforces scope by only showing each agent its own tools.
    session = session_store.load(SESSION_ID) if SESSION_ID else SESSION
    text, is_error = call_tool(None, params.name, params.arguments or {}, session)
    if SESSION_ID:
        session_store.save(SESSION_ID, session)
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=is_error)


server = Server("support-agent-tools", on_list_tools=list_tools, on_call_tool=handle_call)


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(main)
