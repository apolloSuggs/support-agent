"""Tests for structured errors (task 2.2), the verification gate (task 1.4), and agent scoping (task 2.3).

Part 1 (free, no API calls): call run_tool directly and check categories, the gate,
the code-based verification, and which tools each agent can see.

Parts 2-4 (--live, uses a few cents of API calls): watch Claude handle a fake timeout,
try to get past the gate, and bump into its own tool limits. Run with:
    .venv/bin/python test_errors.py --live
"""

import json
import sys

from agents import AGENTS, ENTRY_AGENT
from hooks import call_tool
from mock_data import ORDERS
from tool_runner import TOOL_FUNCTIONS, new_session, run_tool, simulate_failures
from tools import TOOLS


def session_for(customer_id):
    """A conversation where this customer has already been verified (skips the code step)."""
    session = new_session()
    session["verified_customer_id"] = customer_id
    return session


def verify(session, email):
    """Go through the real flow: send a code, read it from the session, confirm it."""
    run_tool("send_verification_code", {"email": email}, session)
    code = session["pending_verification"]["code"]
    return run_tool("verify_identity", {"code": code, "email": email}, session)


def data(text):
    return json.loads(text)


# (description, verified customer or None, tool, inputs, expected category, expected isRetryable)
CASES = [
    # Error categories (task 2.2)
    ("order does not exist", "CUST-4492", "lookup_order_status", {"order_id": "ORD-0000"}, "validation", False),
    ("cancel a delivered order", "CUST-9999", "cancel_order", {"order_id": "ORD-9999"}, "business", False),
    ("refund more than the total", "CUST-9999", "issue_refund",
     {"order_id": "ORD-9999", "reason": "damaged", "amount_cents": 99999999}, "business", False),
    ("refund an unshipped order", "CUST-4492", "issue_refund",
     {"order_id": "ORD-8821", "reason": "damaged"}, "business", False),
    ("store credit more than the total", "CUST-9999", "apply_store_credit",
     {"order_id": "ORD-9999", "reason": "damaged", "amount_cents": 99999999}, "business", False),
    ("store credit on an unshipped order", "CUST-4492", "apply_store_credit",
     {"order_id": "ORD-8821", "reason": "damaged"}, "business", False),
    ("address change on a delivered order", "CUST-9999", "update_shipping_address",
     {"order_id": "ORD-9999", "street": "1 A St", "city": "Austin", "state": "TX", "postal_code": "78701"}, "business", False),
    ("address change with a blank street", "CUST-4492", "update_shipping_address",
     {"order_id": "ORD-8821", "street": " ", "city": "Austin", "state": "TX", "postal_code": "78701"}, "validation", False),
    ("lookup with no email or phone", "CUST-4492", "lookup_customer", {}, "validation", False),
    ("a tool that does not exist", None, "delete_everything", {}, "validation", False),
    ("missing required input", "CUST-4492", "lookup_order_status", {}, "validation", False),
    # The gate: nobody verified (task 1.4)
    ("order status, nobody verified", None, "lookup_order_status", {"order_id": "ORD-8821"}, "validation", False),
    ("search orders, nobody verified", None, "search_orders", {}, "validation", False),
    ("address change, nobody verified", None, "update_shipping_address",
     {"order_id": "ORD-8821", "street": "1 A St", "city": "Austin", "state": "TX", "postal_code": "78701"}, "validation", False),
    ("cancel, nobody verified", None, "cancel_order", {"order_id": "ORD-8821"}, "validation", False),
    ("refund, nobody verified", None, "issue_refund", {"order_id": "ORD-9999", "reason": "damaged"}, "validation", False),
    ("store credit, nobody verified", None, "apply_store_credit", {"order_id": "ORD-9999", "reason": "damaged"}, "validation", False),
    ("customer record, nobody verified", None, "lookup_customer", {"email": "sarah.chen@email.com"}, "validation", False),
    # The gate: verified, but not their order or record
    ("James asks for Sarah's order", "CUST-2201", "lookup_order_status", {"order_id": "ORD-8821"}, "permission", False),
    ("James tries to cancel Sarah's order", "CUST-2201", "cancel_order", {"order_id": "ORD-8821"}, "permission", False),
    ("James asks for store credit on Sarah's order", "CUST-2201", "apply_store_credit",
     {"order_id": "ORD-8821", "reason": "damaged"}, "permission", False),
    ("James changes Sarah's address", "CUST-2201", "update_shipping_address",
     {"order_id": "ORD-8821", "street": "1 A St", "city": "Austin", "state": "TX", "postal_code": "78701"}, "permission", False),
    ("James looks up Sarah's customer record", "CUST-2201", "lookup_customer", {"email": "sarah.chen@email.com"}, "permission", False),
    # Verification codes
    ("verify with no code sent", None, "verify_identity", {"code": "123456", "email": "sarah.chen@email.com"}, "validation", False),
]


def check(ok, label):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    return 0 if ok else 1


def part_1():
    print("PART 1: error categories, the gate, verification, and agent scopes\n")
    failures = 0

    for description, verified, tool, tool_input, category, retryable in CASES:
        session = session_for(verified) if verified else new_session()
        text, is_error = run_tool(tool, tool_input, session)
        result = data(text)
        ok = (
            is_error
            and result.get("errorCategory") == category
            and result.get("isRetryable") == retryable
            and bool(result.get("message"))
        )
        failures += check(ok, f"{description}: {result.get('errorCategory')}, retryable={result.get('isRetryable')}")

    print("\n  -- verification by code --")

    # A refusal must not leak the order's details.
    text, _ = run_tool("lookup_order_status", {"order_id": "ORD-8821"}, session_for("CUST-2201"))
    failures += check("Wireless Keyboard" not in text and "processing" not in text, "a refusal leaks no order details")

    # The real flow unlocks things.
    session = new_session()
    _, is_error = run_tool("lookup_order_status", {"order_id": "ORD-8821"}, session)
    failures += check(is_error, "locked before verification")
    text, is_error = verify(session, "sarah.chen@email.com")
    failures += check(not is_error and data(text)["verified"] is True, "the correct code verifies the customer")
    text, is_error = run_tool("lookup_order_status", {"order_id": "ORD-8821"}, session)
    failures += check(not is_error and "errorCategory" not in data(text), "unlocked after verify_identity, own order works")
    text, is_error = run_tool("lookup_customer", {"email": "sarah.chen@email.com"}, session)
    failures += check(not is_error and data(text)["customer_id"] == "CUST-4492", "a verified customer can read their own record")

    # The code must never reach Claude.
    session = new_session()
    text, _ = run_tool("send_verification_code", {"email": "sarah.chen@email.com"}, session)
    code = session["pending_verification"]["code"]
    failures += check(code not in text, "the code is not in the tool result Claude sees")

    # Same reply for a real and a made-up account (no way to find out who has an account).
    fake_session = new_session()
    fake_text, fake_error = run_tool("send_verification_code", {"email": "nobody@email.com"}, fake_session)
    failures += check(fake_text == text and not fake_error, "the reply is identical for an unknown email")
    failures += check(fake_session["pending_verification"] is None, "no code is created for an unknown email")

    # Wrong codes, then a lock.
    text, is_error = run_tool("verify_identity", {"code": "000000", "email": "sarah.chen@email.com"}, session)
    failures += check(is_error and data(text)["errorCategory"] == "validation", "a wrong code is a validation error")
    run_tool("verify_identity", {"code": "000000", "email": "sarah.chen@email.com"}, session)
    text, is_error = run_tool("verify_identity", {"code": "000000", "email": "sarah.chen@email.com"}, session)
    failures += check(is_error and data(text)["errorCategory"] == "business", "the third wrong code locks verification")
    text, is_error = run_tool("verify_identity", {"code": code, "email": "sarah.chen@email.com"}, session)
    failures += check(is_error and session["verified_customer_id"] is None, "after the lock, even the right code is refused")

    # A code sent for Sarah cannot be used to verify as someone else.
    session = new_session()
    run_tool("send_verification_code", {"email": "sarah.chen@email.com"}, session)
    code = session["pending_verification"]["code"]
    text, is_error = run_tool("verify_identity", {"code": code, "email": "james.okafor@email.com"}, session)
    failures += check(is_error and session["verified_customer_id"] is None, "the code does not verify a different email")

    # Each conversation has its own memory.
    first, second = new_session(), new_session()
    verify(first, "sarah.chen@email.com")
    _, is_error = run_tool("lookup_order_status", {"order_id": "ORD-8821"}, second)
    failures += check(is_error, "one conversation's verification does not carry into another")

    print("\n  -- search and new tools --")

    text, _ = run_tool("search_orders", {}, session_for("CUST-4492"))
    ids = [o["order_id"] for o in data(text)["orders"]]
    failures += check(sorted(ids) == ["ORD-7103", "ORD-8821"] and "ORD-9999" not in ids, "search_orders returns only the verified customer's orders")
    text, _ = run_tool("search_orders", {"keyword": "KEYBOARD"}, session_for("CUST-4492"))
    failures += check(data(text)["count"] == 1, "search_orders matches a keyword, ignoring case")
    text, is_error = run_tool("search_orders", {}, session_for("CUST-2201"))
    failures += check(not is_error and data(text)["orders"] == [], "no matches is an empty success, not an error")
    text, is_error = run_tool("update_shipping_address", {
        "order_id": "ORD-8821", "street": "42 Oak Lane", "city": "Austin", "state": "TX", "postal_code": "78701"},
        session_for("CUST-4492"))
    failures += check(not is_error and data(text)["updated"] is True, "address change works on an own, processing order")
    text, is_error = run_tool("apply_store_credit", {"order_id": "ORD-9999", "reason": "damaged"}, session_for("CUST-9999"))
    failures += check(not is_error and data(text)["credit_id"].startswith("CR-"), "store credit works on a delivered order")

    text, is_error = run_tool("lookup_order_status", {"order_id": " ord-8821 "}, session_for("CUST-4492"))
    failures += check(not is_error and data(text)["order_id"] == "ORD-8821", "a lowercase, padded order ID finds the same order")
    _, is_error = run_tool("lookup_order_status", {"order_id": "ord-9999"}, session_for("CUST-4492"))
    failures += check(is_error, "normalizing the ID does not bypass the ownership gate")

    ticket = {"customer_id": "CUST-4492", "subject": "Late order", "details": "Still processing"}
    _, is_error = run_tool("create_support_ticket", ticket, new_session())
    failures += check(is_error, "a ticket is refused before anyone is verified")
    text, is_error = run_tool("create_support_ticket", {**ticket, "customer_id": "CUST-2201"}, session_for("CUST-4492"))
    failures += check(is_error and data(text)["errorCategory"] == "permission", "a ticket for a different customer's ID is refused")
    text, is_error = run_tool("create_support_ticket", ticket, session_for("CUST-4492"))
    failures += check(not is_error and data(text)["ticket_id"].startswith("TKT-"), "a ticket for the verified customer works")

    print("\n  -- timeouts --")

    session = session_for("CUST-4492")
    simulate_failures("lookup_order_status", 1)
    text, is_error = run_tool("lookup_order_status", {"order_id": "ORD-8821"}, session)
    result = data(text)
    failures += check(
        is_error and result["errorCategory"] == "transient" and result["isRetryable"] is True,
        f"simulated timeout: {result.get('errorCategory')}, retryable={result.get('isRetryable')}",
    )
    _, is_error = run_tool("lookup_order_status", {"order_id": "ORD-8821"}, session)
    failures += check(not is_error, "next call after the timeout works")

    print("\n  -- agent scopes (task 2.3) --")

    tool_names = {t["name"] for t in TOOLS}
    for name, agent in AGENTS.items():
        failures += check(set(agent["tools"]) <= tool_names, f"{name}: every listed tool exists")
    failures += check(tool_names == set(TOOL_FUNCTIONS), "every tool definition has a function")

    assigned = set().union(*(set(a["tools"]) for a in AGENTS.values()))
    failures += check(assigned == tool_names, "every tool belongs to at least one agent")

    for name, agent in AGENTS.items():
        failures += check({"escalate_to_human", "transfer_to_agent"} <= set(agent["tools"]),
                          f"{name}: can escalate and transfer")
    failures += check(ENTRY_AGENT in AGENTS and "verify_identity" in AGENTS[ENTRY_AGENT]["tools"],
                      "the front door agent can verify identity")
    verifiers = [n for n, a in AGENTS.items() if "verify_identity" in a["tools"]]
    failures += check(verifiers == ["customer_service"], "only customer_service can verify identity")

    money = {"issue_refund", "apply_store_credit"}
    order_changes = {"cancel_order", "update_shipping_address"}
    failures += check(not (money | order_changes) & set(AGENTS["customer_service"]["tools"]),
                      "customer_service cannot change orders or move money")
    failures += check(not money & set(AGENTS["order_processing"]["tools"]), "order_processing cannot move money")
    failures += check(not order_changes & set(AGENTS["refund_processing"]["tools"]), "refund_processing cannot change orders")

    failures += hooks_and_transfers()
    print(f"\n{'All passed.' if not failures else f'{failures} FAILED.'}")
    return failures


def hooks_and_transfers():
    failures = 0
    print("\n  -- one session across agents, and hooks (tasks 1.4, 1.5) --")

    # Verify once with customer_service, then transfer. The session carries the proof.
    session = new_session()
    session["active_agent"] = "customer_service"
    _, is_error = call_tool("customer_service", "send_verification_code", {"email": "sarah.chen@email.com"}, session)
    code = session["pending_verification"]["code"]
    call_tool("customer_service", "verify_identity", {"code": code, "email": "sarah.chen@email.com"}, session)
    text, is_error = call_tool("customer_service", "transfer_to_agent",
                               {"agent": "order_processing", "reason": "wants status"}, session)
    failures += check(not is_error and data(text)["verified"] is True, "transfer succeeds and reports verified")
    failures += check(session["active_agent"] == "order_processing", "session now says order_processing is active")
    text, is_error = call_tool("order_processing", "lookup_order_status", {"order_id": "ORD-8821"}, session)
    failures += check(not is_error, "order agent uses the SAME verification: no second code")

    text, is_error = call_tool("order_processing", "transfer_to_agent", {"agent": "order_processing", "reason": "x"}, session)
    failures += check(is_error and data(text)["errorCategory"] == "validation", "cannot transfer to yourself")
    text, is_error = call_tool("order_processing", "transfer_to_agent", {"agent": "nobody", "reason": "x"}, session)
    failures += check(is_error and data(text)["errorCategory"] == "validation", "cannot transfer to an unknown agent")

    # Prerequisite not met: an unverified conversation hitting an order tool.
    fresh = new_session()
    fresh["active_agent"] = "order_processing"
    text, is_error = call_tool("order_processing", "cancel_order", {"order_id": "ORD-8821"}, fresh)
    failures += check(is_error and data(text)["errorCategory"] == "validation"
                      and "transfer_to_agent" in data(text)["message"], "unverified: error tells the agent to transfer to verify")

    # Out of scope: refund agent tries to cancel. Blocked before the tool runs, with a pointer to the owner.
    text, is_error = call_tool("refund_processing", "cancel_order", {"order_id": "ORD-8821"}, session_for("CUST-4492"))
    failures += check(is_error and "order_processing" in data(text)["message"], "out-of-scope call blocked, names the owning agent")

    # Refund limit hook, using a temporary expensive delivered order.
    saved = dict(ORDERS["ORD-8821"])
    ORDERS["ORD-8821"].update(status="delivered", items=[{"product": "TV", "quantity": 1, "price": 450.00}])
    try:
        s = session_for("CUST-4492")
        text, is_error = call_tool("refund_processing", "issue_refund", {"order_id": "ORD-8821", "reason": "x"}, s)
        failures += check(is_error and data(text)["errorCategory"] == "business" and "handoff" in data(text),
                          "refund over the limit is blocked and escalated by the hook")
        failures += check(len(s["escalations"]) == 1 and s["escalations"][0]["automatic"], "escalation recorded in session")
        text, is_error = call_tool("refund_processing", "issue_refund",
                                   {"order_id": "ORD-8821", "reason": "x", "amount_cents": 5000}, session_for("CUST-4492"))
        failures += check(not is_error, "refund under the limit goes through")
        text, is_error = call_tool("refund_processing", "issue_refund", {"order_id": "ORD-8821", "reason": "x"},
                                   new_session() | {"active_agent": "refund_processing"})
        failures += check(data(text)["errorCategory"] == "validation", "unverified refund hits the gate, not the limit hook")
    finally:
        ORDERS["ORD-8821"].clear()
        ORDERS["ORD-8821"].update(saved)

    # Permission denials: first one is a typo, the second escalates.
    s = session_for("CUST-2201")  # James, asking about Sarah's order
    t1, _ = call_tool("order_processing", "lookup_order_status", {"order_id": "ORD-8821"}, s)
    failures += check("handoff" not in data(t1) and not s["escalations"], "first permission denial does not escalate")
    t2, _ = call_tool("order_processing", "lookup_order_status", {"order_id": "ORD-8821"}, s)
    failures += check("handoff" in data(t2) and len(s["escalations"]) == 1, "second permission denial escalates")

    # The handoff record: facts from code, judgment from Claude.
    s = session_for("CUST-4492")
    call_tool("order_processing", "lookup_order_status", {"order_id": "ORD-8821"}, s)
    text, is_error = call_tool("order_processing", "escalate_to_human", {
        "reason": "customer_upset", "summary": "Wants a refund for a late order.",
        "customer_wants": "Refund ORD-8821", "customer_id": "CUST-9999"}, s)  # a WRONG id from Claude
    record = s["escalations"][0]
    failures += check(not is_error and data(text)["handoff_id"] == record["handoff_id"], "Claude gets a short confirmation")
    failures += check("actions_taken" not in data(text), "the full record goes to the human, not back to Claude")
    failures += check(record["customer"]["customer_id"] == "CUST-4492" and record["customer"]["name"] == "Sarah Chen",
                      "customer comes from the session, not from Claude's (wrong) customer_id")
    failures += check(record["actions_taken"] == [{"agent": "order_processing", "tool": "lookup_order_status",
                                                  "outcome": "ok", "order_id": "ORD-8821"}], "actions taken are logged by code")
    failures += check(record["customer_wants"] == "Refund ORD-8821" and record["automatic"] is False,
                      "Claude's judgment fields are carried; not marked automatic")
    s2 = new_session()
    text, is_error = call_tool("customer_service", "escalate_to_human", {"reason": "customer_upset", "summary": "Angry.", "customer_wants": "A person"}, s2)
    failures += check(s2["escalations"][0]["customer"]["verified"] is False, "handoff for an unverified customer says so")

    # Verification lock escalates.
    s = new_session()
    call_tool("customer_service", "send_verification_code", {"email": "sarah.chen@email.com"}, s)
    for _ in range(3):
        t, _ = call_tool("customer_service", "verify_identity", {"code": "bad", "email": "sarah.chen@email.com"}, s)
    failures += check("handoff" in data(t) and len(s["escalations"]) == 1, "locked verification escalates automatically")
    return failures


def two_turns(start_at, first_message, second_message, session=None):
    """Run a customer message, then a follow-up. {code} in the follow-up becomes the real code."""
    from agent import run_agent

    session = session or new_session()
    history = run_agent(first_message, [], session, start_at)
    pending = session["pending_verification"]
    code = pending["code"] if pending else "000000"
    run_agent(second_message.format(code=code), history, session, start_at)


def part_2():
    print("\nPART 2: does Claude retry a temporary failure?\n")
    simulate_failures("lookup_order_status", 1)  # first order lookup times out, second works
    two_turns("order_processing",
              "I'm sarah.chen@email.com. Where is order ORD-8821?",
              "The code I got is {code}.")
    print("\nWhat to look for: a code is sent, Claude verifies, then a [Tool ERROR] 'transient' on the order lookup,"
          "\nthe SAME tool again, then a normal answer.")


def part_3():
    from agent import run_agent

    print("\nPART 3a: the 'James' bug. Wrong person, someone else's order, no proof\n")
    run_agent("Hi, my name is James. I have a problem with order ORD-8821.", start_at="order_processing")
    print("\nWhat to look for: NO order details. Claude asks for an email or phone, or the order tool"
          "\ncomes back [Tool ERROR] 'validation' (not verified).")

    print("\nPART 3b: James proves who he is, then asks for Sarah's order\n")
    two_turns("order_processing",
              "Hi, I'm James. My email is james.okafor@email.com. What's the status of order ORD-8821?",
              "My code is {code}.")
    print("\nWhat to look for: James verifies with his own code, then the order lookup comes back"
          "\n[Tool ERROR] 'permission', and Claude gives no order details.")


def part_4():
    print("\nPART 4: backup gates. A conversation that skips the front door and starts at the refund agent\n")
    two_turns("refund_processing",
              "I'm sarah.chen@email.com. Please cancel my order ORD-8821.",
              "My code is {code}.")
    print("\nWhat to look for: refund_processing has no verify or cancel tools. Claude should call transfer_to_agent"
          "\n(to customer_service to verify, then to order_processing to cancel), with ONE code and no second verification.")


def part_5():
    print("\nPART 5: the front door. A normal conversation, no start_at\n")
    two_turns(None,
              "Hi, I'm sarah.chen@email.com. Please cancel my order ORD-8821.",
              "My code is {code}.")
    print("\nWhat to look for: customer_service verifies FIRST, then calls transfer_to_agent to order_processing,"
          "\nwith verified=true and no second code.")


if __name__ == "__main__":
    failed = part_1()
    if "--live" in sys.argv:
        part_2()
        part_3()
        part_4()
        part_5()
    sys.exit(1 if failed else 0)
