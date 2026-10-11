"""test_coordinator.py — checks for the coordinator (coordinator.py).

Part 1 (free): the setup is what we intend.
Part 2 (--live, a few cents): a scripted two-job conversation. We play the customer.
    .venv/bin/python test_coordinator.py --live
"""

import asyncio
import sys

import coordinator as c

failures = 0


def check(ok, label):
    global failures
    print(("  ok   " if ok else "  FAIL ") + label)
    failures += 0 if ok else 1


def part_1():
    print("\nPART 1: setup (free)\n")
    o = c.options_for_coordinator("t1")
    check("Agent" in o.allowed_tools, "coordinator may use the Agent tool")
    check(set(o.agents) == {"order_specialist", "refund_specialist"}, "two subagents defined")
    deny = asyncio.run(c.scope_hook({"tool_name": c.PREFIX + "cancel_order"}, "x", None))
    check(deny["hookSpecificOutput"]["permissionDecision"] == "deny", "hook: coordinator cannot cancel orders itself")
    deny = asyncio.run(c.scope_hook({"tool_name": c.PREFIX + "cancel_order", "agent_id": "a", "agent_type": "refund_specialist"}, "x", None))
    check(deny["hookSpecificOutput"]["permissionDecision"] == "deny", "hook: refund specialist cannot cancel orders")
    ok = asyncio.run(c.scope_hook({"tool_name": c.PREFIX + "cancel_order", "agent_id": "a", "agent_type": "order_specialist"}, "x", None))
    check(ok == {}, "hook: order specialist may cancel orders")
    refund_tools = c.SUBAGENTS["refund_specialist"].tools
    check(all("lookup" not in t and "cancel" not in t for t in refund_tools), "refund specialist has only money tools")
    check(o.tools == ["Agent"], "only built-in tool is the one that starts subagents (no Bash, no files)")


def part_1b():
    print("\nPART 1b: structured reports are built from real tool results (free)\n")
    led = c.ReportLedger()
    led.record("a1", "mcp__support__issue_refund", {"order_id": "ORD-7103"},
               {"refund_id": "REF-5001", "amount_cents": 4500, "expected_by": "10-14-2026"})
    r = led.build_report("a1", "refund_specialist", "Refunded.")
    check(r["status"] == "success" and r["order_id"] == "ORD-7103", "success report carries status and order ID")
    check(r["results"][0]["refund_id"] == "REF-5001" and r["results"][0]["amount_cents"] == 4500,
          "report carries the tool's own fields, not the model's copy")
    led.record("a2", "mcp__support__cancel_order", {"order_id": "ORD-1"},
               {"errorCategory": "business", "isRetryable": False, "message": "Already shipped."})
    r = led.build_report("a2", "order_specialist", "Could not cancel.")
    check(r["status"] == "failed" and r["error"]["errorCategory"] == "business" and r["results"] == [],
          "failed report carries the structured error and no results")
    led.record("a3", "mcp__support__issue_refund", {"order_id": "ORD-2"}, {"handoff": {"handoff_id": "HO-1"}})
    check(led.build_report("a3", "refund_specialist", "x")["status"] == "needs_human", "handoff becomes needs_human")
    check(led.build_report("zzz", "order_specialist", "x")["status"] == "no_action", "no tool calls = no_action")


async def part_2():
    print("\nPART 2: a two-job request through the coordinator (live)\n")
    convo = c.CoordinatorConversation()
    c.show(await convo.send(
        "Hi, I'm sarah.chen@email.com. Please cancel order ORD-8821, and refund my delivered order ORD-7103 to my card."))
    code = convo.session["outbox"][-1]["text"].split()[-1]  # we play the customer reading their inbox
    events = await convo.send(f"My code is {code}.")
    c.show(events)
    spawns = [e for e in events if e["type"] == "spawn"]
    check(bool(spawns), "coordinator used the Agent tool at all")
    check({e["to"] for e in spawns} == {"order_specialist", "refund_specialist"}, "both specialists were started")
    check(bool(spawns) and all("ORD-" in e["prompt"] and "CUST-4492" in e["prompt"] for e in spawns),
          "every briefing names the customer ID and an order ID (context isolation)")
    sub_calls = [e["name"] for e in events if e["type"] == "tool_call" and e["agent"] != "coordinator"]
    check("cancel_order" in sub_calls and "issue_refund" in sub_calls, "specialists did their own tool calls")
    ok_results = [e for e in events if e["type"] == "tool_result" and not e["is_error"]]
    check(any('"cancelled": true' in e["content"] for e in ok_results), "order was cancelled")
    check(convo.session["verified_customer_id"] == "CUST-4492", "gate: verification is in the stored session")
    reports = {e["report"]["agent"]: e["report"] for e in events if e["type"] == "report"}
    check(set(reports) == {"order_specialist", "refund_specialist"}, "a structured report arrived for each specialist")
    check(all(r["status"] == "success" for r in reports.values()), "both reports say success")
    refund = reports.get("refund_specialist", {})
    check(any(x.get("refund_id") == "REF-5001" and x.get("amount_cents") == 4500 for x in refund.get("results", [])),
          "refund report holds the real refund_id and amount from the tool")
    final = [e["text"] for e in events if e["type"] == "assistant" and e["agent"] == "coordinator"][-1]
    check("REF-5001" in final and "45" in final, "the customer's reply uses the report's refund ID and amount")


if __name__ == "__main__":
    part_1()
    part_1b()
    if "--live" in sys.argv:
        asyncio.run(part_2())
    print("\nAll checks passed." if not failures else f"\n{failures} check(s) FAILED.")
    sys.exit(1 if failures else 0)
