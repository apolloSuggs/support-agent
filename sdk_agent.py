"""sdk_agent.py — the support agents run by the Claude Agent SDK, using our MCP server (tasks 1.5, 2.4).

Compare with agent.py. There WE wrote the loop and called the API. Here the SDK runs the loop and we
only describe the setup:
  - system_prompt            which agent this turn is (agents.py)
  - mcp_servers              where the tools come from (mcp_server.py)
  - tools=[]                 no built-in tools (no Bash, no file access) for a customer-facing agent
  - disallowed_tools         hides every tool outside this agent's list (task 2.3 scoping)
  - hooks (PreToolUse)       a second layer: deny anything out of scope, with a reason Claude can read
  - setting_sources=[]       do not load CLAUDE.md or personal settings into a customer-facing agent

The gate, the refund limit and the auto-escalation still live in mcp_server.py, so they hold no matter
which client connects. This file only does the parts a client should do: pick the agent and its tools.

How a handoff works here: transfer_to_agent records the change in the stored session. The SDK turn ends
(the old agent tells the customer), then this file starts the next turn as the new agent, resuming the
same SDK conversation so the history carries over.

Run a chat:  .venv/bin/python sdk_agent.py
"""

import asyncio
import sys
import uuid
from pathlib import Path

import claude_agent_sdk as sdk
from dotenv import load_dotenv

import session_store
from agents import AGENTS, ENTRY_AGENT
from tool_runner import new_session
from tools import TOOLS

load_dotenv()  # ANTHROPIC_API_KEY from .env (never printed)

ROOT = Path(__file__).parent
MODEL = "claude-haiku-4-5-20251001"
SERVER = "support"                      # the name we give the MCP server in this config
PREFIX = f"mcp__{SERVER}__"             # how the SDK names MCP tools: mcp__<server>__<tool>
ALL_TOOLS = [t["name"] for t in TOOLS]
MAX_HOPS = 4                            # most agent-to-agent handoffs in one customer message


def make_scope_hook(agent_name):
    """A PreToolUse hook. The SDK calls it before every tool; returning 'deny' stops the call."""

    async def scope_hook(input_data, tool_use_id, context):
        tool = input_data["tool_name"]
        name = tool.removeprefix(PREFIX)
        if tool.startswith(PREFIX) and name not in AGENTS[agent_name]["tools"]:
            owners = [n for n, a in AGENTS.items() if name in a["tools"]]
            hint = f" It belongs to: {', '.join(owners)}. Use transfer_to_agent." if owners else ""
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"{name} is not available to the {agent_name} agent.{hint}",
                }
            }
        return {}  # empty means: no opinion, carry on

    return scope_hook


def options_for(agent_name, conversation_id, resume=None):
    own = set(AGENTS[agent_name]["tools"])
    return sdk.ClaudeAgentOptions(
        system_prompt=AGENTS[agent_name]["system_prompt"],
        model=MODEL,
        cwd=str(ROOT),
        tools=[],
        setting_sources=[],
        strict_mcp_config=True,  # use only the servers listed below, not any others on this machine
        mcp_servers={
            SERVER: {
                "type": "stdio",
                "command": sys.executable,
                "args": [str(ROOT / "mcp_server.py")],
                # SESSION_ID makes the server keep the session in .sessions/, shared across turns and agents
                "env": {"SESSION_ID": conversation_id},
            }
        },
        allowed_tools=[PREFIX + n for n in sorted(own)],
        disallowed_tools=[PREFIX + n for n in ALL_TOOLS if n not in own],
        hooks={"PreToolUse": [sdk.HookMatcher(hooks=[make_scope_hook(agent_name)])]},
        resume=resume,
        max_turns=12,  # backup cap on tool rounds in one turn, like MAX_PASSES in agent.py
    )


def _result_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return str(content)


class Conversation:
    """One customer conversation: an ID, the stored session, and the SDK conversation to resume."""

    def __init__(self, start_at=None):
        self.id = uuid.uuid4().hex[:12]
        self.sdk_session = None
        session = new_session()
        session["active_agent"] = start_at or ENTRY_AGENT  # every chat starts at the front door
        session_store.save(self.id, session)

    @property
    def session(self):
        return session_store.load(self.id)

    async def send(self, message):
        """Handle one customer message. Returns a list of events (text, tool calls, handoffs) to show."""
        events = []
        prompt = message
        for _ in range(MAX_HOPS):
            agent_name = self.session["active_agent"]
            escalations_before = len(self.session["escalations"])
            await self._turn(agent_name, prompt, events)

            after = self.session
            for record in after["escalations"][escalations_before:]:
                events.append({"type": "handoff", "record": record})
            if after["active_agent"] == agent_name:
                break  # nobody took over: this customer message is done
            reason = after["transfers"][-1]["reason"]
            events.append({"type": "transfer", "to": after["active_agent"], "reason": reason})
            prompt = f"You are now the {after['active_agent']} agent. Carry on with the customer's request: {reason}"
        return events

    async def _turn(self, agent_name, prompt, events):
        options = options_for(agent_name, self.id, self.sdk_session)
        async for message in sdk.query(prompt=prompt, options=options):
            if isinstance(message, sdk.AssistantMessage):
                for block in message.content:
                    if isinstance(block, sdk.TextBlock) and block.text.strip():
                        events.append({"type": "assistant", "agent": agent_name, "text": block.text})
                    elif isinstance(block, sdk.ToolUseBlock):
                        events.append({"type": "tool_call", "agent": agent_name, "id": block.id,
                                       "name": block.name.removeprefix(PREFIX), "input": block.input})
            elif isinstance(message, sdk.UserMessage) and isinstance(message.content, list):
                for block in message.content:
                    if isinstance(block, sdk.ToolResultBlock):
                        events.append({"type": "tool_result", "id": block.tool_use_id,
                                       "is_error": bool(block.is_error), "content": _result_text(block.content)})
            elif isinstance(message, sdk.ResultMessage):
                self.sdk_session = message.session_id  # resume this conversation on the next turn


def show(events):
    """Plain-text view of events, for the terminal."""
    for e in events:
        if e["type"] == "assistant":
            print(f"\n[{e['agent']}] {e['text']}")
        elif e["type"] == "tool_call":
            print(f"\n[Tool call]   {e['name']}({e['input']})")
        elif e["type"] == "tool_result":
            print(f"[Tool {'ERROR' if e['is_error'] else 'result'}] {e['content']}")
        elif e["type"] == "transfer":
            print(f"\n[Transfer] now talking to: {e['to']}  ({e['reason']})")
        elif e["type"] == "handoff":
            print(f"\n[Handoff to human] {e['record']}")


async def chat():
    print("Chatting with support through the Agent SDK. Type as the customer. Empty line quits.")
    conversation = Conversation()
    message = " ".join(sys.argv[1:]) or input("\nYou: ")
    while message.strip():
        show(await conversation.send(message))
        outbox = conversation.session["outbox"]
        if outbox:
            print(f"\n[Your inbox] latest: {outbox[-1]['text']}  (to {outbox[-1]['to']})")
        message = input("\nYou: ")


if __name__ == "__main__":
    asyncio.run(chat())
