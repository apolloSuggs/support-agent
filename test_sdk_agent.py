"""Tests for the Agent SDK client (sdk_agent.py).

Part 1 is free (no API calls): how the options are built and the PreToolUse scope hook.
Part 2 (--live, a few cents): a scripted conversation through the SDK and our MCP server.
    .venv/bin/python test_sdk_agent.py --live
"""

import asyncio
import sys

from agents import AGENTS
from sdk_agent import PREFIX, Conversation, make_scope_hook, options_for, show
from tools import TOOLS

failures = 0


def check(ok, label):
    global failures
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        failures += 1


def part_1():
    print("PART 1: options and the scope hook (free)\n")
    for name, agent in AGENTS.items():
        o = options_for(name, "x")
        check(o.tools == [], f"{name}: no built-in tools")
        check(set(o.allowed_tools) == {PREFIX + t for t in agent["tools"]}, f"{name}: allowed = its own tools")
        check(set(o.allowed_tools) | set(o.disallowed_tools) == {PREFIX + t["name"] for t in TOOLS},
              f"{name}: every tool is either allowed or hidden")
        check(o.setting_sources == [] and o.strict_mcp_config, f"{name}: no settings loaded, only our MCP server")
    hook = make_scope_hook("refund_processing")
    deny = asyncio.run(hook({"tool_name": PREFIX + "cancel_order"}, "id1", None))
    out = deny["hookSpecificOutput"]
    check(out["permissionDecision"] == "deny" and "order_processing" in out["permissionDecisionReason"],
          "hook denies an out-of-scope tool and names the owner")
    allow = asyncio.run(hook({"tool_name": PREFIX + "issue_refund"}, "id2", None))
    check(allow == {}, "hook stays quiet for an in-scope tool")


async def part_2():
    print("\nPART 2: a conversation through the Agent SDK and the MCP server (live)\n")
    convo = Conversation()
    events = await convo.send("Hi, I'm sarah.chen@email.com. Please cancel my order ORD-8821.")
    show(events)
    code = convo.session["outbox"][-1]["text"].split()[-1]  # we play the customer reading their inbox
    events = await convo.send(f"My code is {code}.")
    show(events)
    names = [e["name"] for e in events if e["type"] == "tool_call"]
    check("verify_identity" in names, "customer_service verified with the real code")
    check(any(e["type"] == "transfer" and e["to"] == "order_processing" for e in events), "handed off to order_processing")
    check(convo.session["verified_customer_id"] == "CUST-4492", "verification is in the stored session")
    events = await convo.send("I changed my mind.")
    show(events)
    cancelled = [e for e in events if e["type"] == "tool_result" and '"cancelled": true' in e["content"]]
    check(bool(cancelled), "order_processing cancelled the order without asking for a second code")
    check(not any(e["type"] == "tool_call" and e["name"] in ("send_verification_code", "verify_identity") for e in events),
          "no second verification")


if __name__ == "__main__":
    part_1()
    if "--live" in sys.argv:
        asyncio.run(part_2())
    print(f"\n{'All passed.' if not failures else f'{failures} FAILED.'}")
    sys.exit(1 if failures else 0)
