"""Hooks: code that wraps EVERY tool call (exam task 1.5).

A hook is a checkpoint the loop passes through, so a rule holds no matter what Claude decides.
  before_tool - runs BEFORE the tool. It can block the call (the tool never runs).
  after_tool  - runs AFTER the tool. It can act on the result (here: escalate to a human).

Hooks can only act on things code can SEE: which tool was called, an error category, an amount.
They cannot judge what a customer MEANT. That is why the triggers below are all things in the data.
"""

import json

from agents import AGENTS
from tool_runner import (
    ORDERS,
    _error,
    build_handoff,
    order_total_cents,
    run_tool,
)

REFUND_LIMIT_CENTS = 10000       # above $100.00 a person must approve
MAX_PERMISSION_DENIALS = 2       # the second "not yours" in one conversation goes to a human
MONEY_TOOLS = {"issue_refund", "apply_store_credit"}


def _auto_escalate(session, reason, summary):
    """The hook performs the handoff itself. Claude does not have to remember to."""
    return build_handoff(
        session, reason, summary,
        suggested_next_step="Review the actions taken and contact the customer.",
        automatic=True,
    )


def before_tool(agent_name, tool_name, tool_input, session):
    """Return an error dict to BLOCK the call, or None to let it through."""
    # 1. Scope: this tool is not on this agent's list. Say who owns it instead of a dead end.
    #    agent_name is None when called from the MCP server, which does not know which agent is asking:
    #    scope is then the client's job (it only shows each agent its own tools).
    if agent_name is not None and tool_name not in AGENTS[agent_name]["tools"]:
        owners = [name for name, a in AGENTS.items() if tool_name in a["tools"]]
        hint = f" It belongs to: {', '.join(owners)}. Use transfer_to_agent." if owners else ""
        return _error("validation", f"{tool_name} is not available to the {agent_name} agent.{hint}")

    # 2. Refund limit: a large amount never runs. The hook hands it to a human by itself.
    #    (A verified customer is required first, so unverified calls fall through to the gate.)
    if tool_name in MONEY_TOOLS and session["verified_customer_id"] is not None:
        order = ORDERS.get(tool_input.get("order_id"))
        if order is not None and order["customer_id"] == session["verified_customer_id"]:
            amount = tool_input.get("amount_cents") or order_total_cents(order)  # no amount = whole order
            if amount > REFUND_LIMIT_CENTS:
                handoff = _auto_escalate(
                    session, "other",
                    f"{tool_name} for {amount} cents on {order['order_id']} is over the "
                    f"{REFUND_LIMIT_CENTS}-cent limit and needs human approval.",
                )
                error = _error(
                    "business",
                    f"Amounts over ${REFUND_LIMIT_CENTS / 100:.2f} need human approval. "
                    "A person has been notified automatically. Tell the customer someone will follow up.",
                )
                error["handoff"] = handoff
                return error
    return None


def after_tool(agent_name, tool_name, tool_input, result, session):
    """Look at the result and act on it. Returns the (possibly extended) result dict."""
    category = result.get("errorCategory")

    # Log what happened (not codes or message text) so any later handoff can say what was done.
    if tool_name not in ("escalate_to_human", "transfer_to_agent"):
        entry = {"agent": agent_name, "tool": tool_name, "outcome": category or "ok"}
        if tool_input.get("order_id"):
            entry["order_id"] = tool_input["order_id"]
        session["actions"].append(entry)

    # A locked verification always goes to a human: the customer failed the code three times.
    if tool_name == "verify_identity" and category == "business":
        result["handoff"] = _auto_escalate(session, "other", "Verification locked after wrong codes.")
        result["message"] += " A person has been notified automatically."

    # One wrong order number can be a typo. The second denial in a conversation looks like probing.
    if category == "permission":
        session["permission_denials"] += 1
        if session["permission_denials"] >= MAX_PERMISSION_DENIALS:
            result["handoff"] = _auto_escalate(
                session, "other", "Repeated attempts to reach records that are not the verified customer's."
            )
            result["message"] += " A person has been notified automatically. Do not try other records."
    return result


def call_tool(agent_name, tool_name, tool_input, session):
    """before hook, then the tool (with the gate), then after hook. Returns (text, is_error)."""
    blocked = before_tool(agent_name, tool_name, tool_input, session)
    if blocked is not None:
        return json.dumps(blocked), True
    text, is_error = run_tool(tool_name, tool_input, session)
    result = after_tool(agent_name, tool_name, tool_input, json.loads(text), session)
    return json.dumps(result), "errorCategory" in result
