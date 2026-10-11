"""coordinator.py — the hub-and-spoke version of the support agent (tasks 1.2, 1.3), on the Claude Agent SDK.

Compare with sdk_agent.py. There, agents HAND the customer on to each other (no boss). Here ONE coordinator
talks to the customer, verifies who they are, and SENDS WORK OUT to subagents, then writes the final reply:

    customer  <->  coordinator  --Agent tool-->  order_specialist   (orders, no money)
                                --Agent tool-->  refund_specialist  (money, narrowest access)

What the course and the guide teach, and where it shows up below:
  - AgentDefinition          a subagent is a description + prompt + tool list (SUBAGENTS below)
  - the Agent tool           how the coordinator starts a subagent. The guide calls it the "Task" tool; the
                             SDK accepts "Agent" and reports it as "Task". It must be in tools AND allowed_tools
                             (we found out the hard way: tools=[] removes it and the coordinator cannot delegate).
  - context isolation        a subagent starts BLANK. It sees only its own prompt and what the coordinator writes
                             in the Agent call. The coordinator prompt below tells it to write a full briefing.
  - parallel subagents       several Agent calls in ONE reply run at the same time
  - gate stays in code       the verified customer lives in the stored session (session_store), read by the MCP
                             server. Subagents never inherit the coordinator's chat, yet the gate still holds
                             because it is not in anyone's context window.

Run a chat:  .venv/bin/python coordinator.py
"""

import asyncio
import json
import sys
import uuid

import claude_agent_sdk as sdk

import session_store
from sdk_agent import MODEL, PREFIX, ROOT, SERVER, _result_text
from tool_runner import new_session

# Coordinator keeps the front-door tools (verification, help, tickets, human escalation) and the Agent tool.
COORDINATOR_TOOLS = [
    "send_verification_code", "verify_identity", "lookup_customer",
    "search_help_articles", "create_support_ticket", "escalate_to_human",
]

# Each subagent is an AgentDefinition: what it is for (description), how it behaves (prompt), what it may use (tools).
SUBAGENTS = {
    "order_specialist": sdk.AgentDefinition(
        description="Checks, searches, re-addresses or cancels customer orders. Never touches money.",
        prompt=(
            "You are the order specialist. You get a briefing from the coordinator with the customer ID, the "
            "order IDs and the exact job. Do only that job with your tools. Reply with ONE plain "
            "sentence saying what you did or found. The system attaches the exact tool results to your report "
            "itself, so do not copy IDs or amounts into JSON. If a tool returns an error, say so in the sentence. "
            "You cannot verify identity or refund anyone. You cannot talk to the customer, so never ask questions: "
            "for an optional detail or a reason code use 'other'. If something truly required is missing, say exactly what is missing."
        ),
        tools=[PREFIX + n for n in ["lookup_order_status", "search_orders", "update_shipping_address", "cancel_order"]],
        model="haiku",
        background=False,   # wait for the report; by default the SDK launches subagents in the background
    ),
    "refund_specialist": sdk.AgentDefinition(
        description="Issues a cash refund or store credit for an order that was already charged.",
        prompt=(
            "You are the refund specialist. You get a briefing from the coordinator with the customer ID, the "
            "order ID and whether the customer wants a refund or store credit. Do only that job with your tools. "
            "Reply with ONE plain sentence saying what happened. The system attaches the exact tool results to your "
            "report itself, so do not copy IDs or amounts into JSON. If a tool returns an error or says a human must "
            "review it, say so in the sentence. You cannot look up orders or verify identity. You cannot talk to the customer, "
            "so never ask questions: for an optional detail or a reason code use 'other'. If something truly required "
            "is missing, say exactly what is missing."
        ),
        tools=[PREFIX + n for n in ["issue_refund", "apply_store_credit"]],
        model="haiku",
        background=False,   # wait for the report; by default the SDK launches subagents in the background
    ),
}

SYSTEM_PROMPT = (
    "You are the support coordinator. You are the only agent that talks to the customer. "
    "1) Find out what they need. 2) Verify them first: send_verification_code, ask for the 6-digit code, "
    "verify_identity. General policy questions can be answered without verifying. "
    "3) Once verified, split the request into jobs and give each job to a specialist with the Agent tool: "
    "order_specialist for orders, refund_specialist for money. If the jobs do not depend on each other, make all the "
    "Agent calls in the SAME reply so they run in parallel. If one needs another's result (for example a refund only "
    "after an order is confirmed shipped), do them one after the other. "
    "Start every job that is ready right away; do not hold one back to ask about another. Do not ask about optional details such as a reason code: the specialist can use 'other'. Only ask the customer for something a job truly cannot run without. "
    "A specialist starts with NOTHING: it cannot see this conversation. So every Agent prompt must be a full briefing: "
    "the customer ID, the exact order IDs, what to do, and what to report back. Never write 'the order we discussed'. "
    "Each specialist's answer comes back with a STRUCTURED REPORT built by the system from the real tool results. "
    "Take every ID, amount and date from that report, never from memory. A report with status no_action means the specialist "
    "could not act: read its summary, ask the customer for what is missing, then brief the specialist again. "
    "4) Read each specialist's report, then write ONE clear reply to the customer covering everything, and say "
    "plainly if any part failed or was sent to a human. Use escalate_to_human for a live person, disputes or policy exceptions. "
    "Be brief and friendly."
)


async def scope_hook(input_data, tool_use_id, context):
    """PreToolUse hook (task 2.3 across agents). The SDK tells us WHO is calling: agent_type is the subagent's
    name inside a subagent, and missing on the coordinator's own thread. We could not simply hide the specialist
    tools from the coordinator with disallowed_tools: that setting is global, so the specialists lost them too."""
    tool = input_data["tool_name"]
    if not tool.startswith(PREFIX):
        return {}
    name = tool.removeprefix(PREFIX)
    caller = input_data.get("agent_type") if input_data.get("agent_id") else "coordinator"
    allowed = [t.removeprefix(PREFIX) for t in SUBAGENTS[caller].tools] if caller in SUBAGENTS \
        else COORDINATOR_TOOLS
    if name in allowed:
        return {}
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": f"{name} is not available to the {caller}. Give that job to the right specialist.",
    }}


def _parse_tool_response(response):
    """MCP tool responses arrive as a list of text blocks. Our tools put JSON in the text."""
    text = "".join(b.get("text", "") for b in response if isinstance(b, dict)) if isinstance(response, list) else str(response)
    try:
        return json.loads(text)
    except ValueError:
        return {"raw": text}


class ReportLedger:
    """Keeps the REAL result of every tool a subagent called, keyed by the subagent's id.

    Why: the course asks the model to copy url/title/date into JSON. A model can drop or change a field when it
    copies. Here CODE records what the tools actually returned and attaches it to the report, so nothing depends
    on the model remembering.
    """

    def __init__(self):
        self.calls = {}      # agent_id -> [{"tool", "input", "result"}]
        self.reports = []    # finished structured reports, in order

    def record(self, agent_id, tool, tool_input, result):
        self.calls.setdefault(agent_id, []).append({"tool": tool.removeprefix(PREFIX), "input": tool_input, "result": result})

    def build_report(self, agent_id, agent_type, summary):
        calls = self.calls.get(agent_id, [])
        error = next((c["result"] for c in calls if isinstance(c["result"], dict) and "errorCategory" in c["result"]), None)
        handed_off = any(isinstance(c["result"], dict) and ("handoff" in c["result"] or c["result"].get("escalated")) for c in calls)
        report = {
            "agent": agent_type,
            "status": "needs_human" if handed_off else "failed" if error else "success" if calls else "no_action",
            "order_id": next((c["input"].get("order_id") for c in calls if c["input"].get("order_id")), None),
            "tool_calls": [{"tool": c["tool"], "input": c["input"]} for c in calls],
            "results": [c["result"] for c in calls if not (isinstance(c["result"], dict) and "errorCategory" in c["result"])],
            "error": error,
            "summary": summary,
        }
        self.reports.append(report)
        return report


def make_report_hooks(ledger):
    """Two PostToolUse hooks. One records each subagent tool result; one builds the report when the subagent finishes."""

    async def record_hook(input_data, tool_use_id, context):
        if input_data.get("agent_id"):  # only calls made inside a subagent
            ledger.record(input_data["agent_id"], input_data["tool_name"], input_data.get("tool_input", {}),
                          _parse_tool_response(input_data.get("tool_response")))
        return {}

    async def report_hook(input_data, tool_use_id, context):
        response = input_data.get("tool_response")
        try:
            body = json.loads(response) if isinstance(response, str) else dict(response)
        except (ValueError, TypeError):
            return {}
        agent_id = body.get("agentId")
        if not agent_id:
            return {}
        summary = " ".join(b.get("text", "") for b in body.get("content", []) if isinstance(b, dict))
        report = ledger.build_report(agent_id, body.get("agentType") or input_data.get("tool_input", {}).get("subagent_type"), summary)
        return {"hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "STRUCTURED REPORT (built by the system from the real tool results):\n" + json.dumps(report),
        }}

    return record_hook, report_hook


def options_for_coordinator(conversation_id, resume=None, ledger=None):
    own = [PREFIX + n for n in COORDINATOR_TOOLS]
    specialist_tools = [t for d in SUBAGENTS.values() for t in d.tools]
    record_hook, report_hook = make_report_hooks(ledger or ReportLedger())
    return sdk.ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        model=MODEL,
        cwd=str(ROOT),
        tools=["Agent"],               # the ONLY built-in tool: the one that starts subagents. tools=[] would remove it too.
        setting_sources=[],
        strict_mcp_config=True,
        mcp_servers={SERVER: {"type": "stdio", "command": sys.executable, "args": [str(ROOT / "mcp_server.py")],
                              "env": {"SESSION_ID": conversation_id}}},   # same stored session for every process
        agents=SUBAGENTS,
        allowed_tools=["Agent"] + own + specialist_tools,   # the guide: allowedTools must include the spawn tool
        disallowed_tools=[PREFIX + "transfer_to_agent"],     # handoffs belong to the other design, not this one
        hooks={
            "PreToolUse": [sdk.HookMatcher(hooks=[scope_hook])],  # who may call what: see scope_hook
            "PostToolUse": [sdk.HookMatcher(matcher=PREFIX + ".*", hooks=[record_hook]),      # remember real tool results
                            sdk.HookMatcher(matcher="Agent|Task", hooks=[report_hook])],      # build the report from them
        },
        env={"CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1"},  # subagents run in the foreground: the Agent call waits for the report
        resume=resume,
        max_turns=20,
    )


class CoordinatorConversation:
    """One customer conversation run by a coordinator. Same shape as sdk_agent.Conversation."""

    def __init__(self):
        self.id = uuid.uuid4().hex[:12]
        self.sdk_session = None
        self.ledger = ReportLedger()
        session_store.save(self.id, new_session())

    @property
    def session(self):
        return session_store.load(self.id)

    async def send(self, message):
        events = []
        escalations_before = len(self.session["escalations"])
        who = {}  # tool_use_id of an Agent call -> subagent name, so subagent steps can be labelled
        reports_before = len(self.ledger.reports)
        async for m in sdk.query(prompt=message, options=options_for_coordinator(self.id, self.sdk_session, self.ledger)):
            parent = getattr(m, "parent_tool_use_id", None)
            label = who.get(parent, "coordinator") if parent else "coordinator"
            if isinstance(m, sdk.AssistantMessage):
                for b in m.content:
                    if isinstance(b, sdk.TextBlock) and b.text.strip():
                        events.append({"type": "assistant", "agent": label, "text": b.text})
                    elif isinstance(b, sdk.ToolUseBlock):
                        if b.name in ("Agent", "Task"):
                            who[b.id] = b.input.get("subagent_type", "subagent")
                            events.append({"type": "spawn", "id": b.id, "to": who[b.id], "prompt": b.input.get("prompt", "")})
                        else:
                            events.append({"type": "tool_call", "agent": label, "id": b.id,
                                           "name": b.name.removeprefix(PREFIX), "input": b.input})
            elif isinstance(m, sdk.UserMessage) and isinstance(m.content, list):
                for b in m.content:
                    if isinstance(b, sdk.ToolResultBlock):
                        events.append({"type": "tool_result", "agent": label, "id": b.tool_use_id,
                                       "is_error": bool(b.is_error), "content": _result_text(b.content)})
            elif isinstance(m, sdk.ResultMessage):
                self.sdk_session = m.session_id
        for report in self.ledger.reports[reports_before:]:
            events.append({"type": "report", "report": report})
        for record in self.session["escalations"][escalations_before:]:
            events.append({"type": "handoff", "record": record})
        return events


def show(events):
    for e in events:
        t = e["type"]
        if t == "spawn":
            print(f"\n[Coordinator -> {e['to']}] briefing:\n    {e['prompt']}")
        elif t == "assistant":
            print(f"\n[{e['agent']}] {e['text']}")
        elif t == "tool_call":
            print(f"   [{e['agent']} tool call] {e['name']}({e['input']})")
        elif t == "tool_result":
            print(f"   [{e['agent']} tool {'ERROR' if e['is_error'] else 'result'}] {e['content'][:300]}")
        elif t == "report":
            print(f"\n[Structured report: {e['report']['agent']}]\n{json.dumps(e['report'], indent=2)}")
        elif t == "handoff":
            print(f"\n[Handoff to human] {e['record']}")


async def chat():
    print("Chatting with the coordinator (Agent SDK). Type as the customer. Empty line quits.")
    conversation = CoordinatorConversation()
    message = " ".join(sys.argv[1:]) or input("\nYou: ")
    while message.strip():
        show(await conversation.send(message))
        outbox = conversation.session["outbox"]
        if outbox:
            print(f"\n[Your inbox] latest: {outbox[-1]['text']}  (to {outbox[-1]['to']})")
        message = input("\nYou: ")


if __name__ == "__main__":
    asyncio.run(chat())
