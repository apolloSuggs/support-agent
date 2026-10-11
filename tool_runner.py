"""tool_runner.py — the code that actually EXECUTES our tools.

Remember the split:
  - tools.py        = the MENU. Tells Claude what each tool is for and what inputs it takes.
  - tool_runner.py  = the KITCHEN. Does the real work when Claude asks for a tool.

Claude never runs anything itself. It replies with a "tool_use" block saying
"call lookup_order_status with order_id='ORD-8821'". Our code finds the matching
function below, runs it, and sends the result back to Claude as a "tool_result".

Right now every function reads from mock_data.py. For a real client, you would
swap the insides of these functions to call their real database or API. The
function names, inputs, and return shapes would stay the same, so nothing else
in the agent has to change.
"""

import json
import secrets
import sys
from datetime import date, timedelta

from agents import AGENTS
from mock_data import CUSTOMERS, ORDERS

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


# The four kinds of failure (exam task 2.2). The category tells Claude WHY it failed:
#   transient  = temporary problem (timeout, service down). Trying again may work.
#   validation = the input was wrong or points at nothing (bad ID). Fix the input first.
#   business   = the input was fine but a policy rule says no (cancel a shipped order).
#   permission = the agent is not allowed to do this (an order that is not the verified customer's).
# Only transient errors are worth retrying. Retrying the others can never succeed.
RETRYABLE_CATEGORIES = {"transient"}


def _error(category, message):
    """Build a structured error result.

    We RETURN errors (instead of raising exceptions) so Claude can read them
    and decide what to do: retry, ask the customer, or explain a policy.
    A crash would just break the agent loop.

    Every error has the same three fields:
      errorCategory - why it failed (see above)
      isRetryable   - True only when trying the same call again could work
      message       - plain English Claude can pass on to the customer
    """
    return {
        "errorCategory": category,
        "isRetryable": category in RETRYABLE_CATEGORIES,
        "message": message,
    }


# --- Test helper: lets us fake a temporary failure -------------------------
# Our mock data never times out, so we need a way to make it happen on purpose.
# simulate_failures("lookup_order_status", 1) makes the NEXT call to that tool
# fail once with a timeout. Then the following call works normally.
_forced_failures = {}


def simulate_failures(tool_name, times=1):
    _forced_failures[tool_name] = times


def _maybe_fail(tool_name):
    if _forced_failures.get(tool_name, 0) > 0:
        _forced_failures[tool_name] -= 1
        raise TimeoutError("simulated timeout")


def _future_date(days):
    """Today plus N days, formatted MM-DD-YYYY (our project's date format)."""
    return (date.today() + timedelta(days=days)).strftime("%m-%d-%Y")


# Simple counters so each new ticket/refund gets its own ID while the program runs.
_ticket_counter = 1000
_refund_counter = 5000
_credit_counter = 9000
_handoff_counter = 100


# ---------------------------------------------------------------------------
# One function per tool. Each takes the same inputs we declared in tools.py
# and returns a dictionary.
# ---------------------------------------------------------------------------


def _find_customer(email=None, phone=None):
    """Find a customer record by email or phone, or None. Used by several tools and by the gate."""
    for customer in CUSTOMERS.values():
        # Compare emails ignoring upper/lower case: 'Sarah@Email.com' == 'sarah@email.com'.
        email_matches = email and customer["email"].lower() == email.lower()
        phone_matches = phone and customer["phone"] == phone
        if email_matches or phone_matches:
            return customer
    return None


MAX_CODE_ATTEMPTS = 3


def send_verification_code(email=None, phone=None, session=None):
    # The code is made and remembered by OUR code. It is never put in the result,
    # so Claude can never read it and "verify" someone who does not have it.
    if not email and not phone:
        return _error("validation", "Provide either an email address or a phone number.")

    customer = _find_customer(email, phone)
    if customer is not None:
        code = f"{secrets.randbelow(1_000_000):06d}"  # secrets, not random: safe for security codes
        session["pending_verification"] = {
            "customer_id": customer["customer_id"],
            "code": code,
            "attempts": 0,
        }
        # MOCK: a real system would send an email or text. We print it (to stderr, so it can never
        # corrupt an MCP server's stdout, which carries the protocol messages) so YOU, playing
        # the customer, can read it and type it in. Claude does not see this line.
        destination = customer["email"] if email else customer["phone"]
        session["outbox"].append({"to": destination, "text": f"Your verification code is {code}"})
        print(f"\n[MOCK MESSAGE to {destination}] Your verification code is {code}", file=sys.stderr)

    # Same reply whether or not an account matched, so nobody can use this tool
    # to find out who has an account.
    return {
        "sent": True,
        "message": "If an account matches, a 6-digit code has been sent to it. Ask the customer for the code.",
    }


def verify_identity(code, email=None, phone=None, session=None):
    pending = session["pending_verification"]
    if pending is None:
        return _error("validation", "No code is waiting. Call send_verification_code first.")
    if not email and not phone:
        return _error("validation", "Provide the email address or phone number the code was sent to.")

    customer = _find_customer(email, phone)
    if customer is None or customer["customer_id"] != pending["customer_id"]:
        return _error("validation", "That email or phone number is not the one the code was sent to.")

    if pending["attempts"] >= MAX_CODE_ATTEMPTS:
        return _error(
            "business",
            "Verification is locked after too many wrong codes. Do not try again. "
            "Hand the customer to a human with escalate_to_human.",
        )

    if str(code).strip() != pending["code"]:
        pending["attempts"] += 1
        left = MAX_CODE_ATTEMPTS - pending["attempts"]
        if left == 0:
            return _error(
                "business",
                "That code is wrong and verification is now locked. Do not try again. "
                "Hand the customer to a human with escalate_to_human.",
            )
        return _error("validation", f"That code is not correct. {left} attempts left. Ask the customer to re-check it.")

    # Success. The CODE records who is verified, not Claude.
    session["verified_customer_id"] = customer["customer_id"]
    session["pending_verification"] = None
    return {"verified": True, "customer_id": customer["customer_id"], "name": customer["name"]}


def lookup_customer(email=None, phone=None):
    # In tools.py, "required" is [] for this tool, so Claude is allowed to send
    # neither field. The schema can't say "at least one of these", so WE enforce it here.
    # (The gate has already made sure the customer is verified and that this is THEIR record.)
    if not email and not phone:
        return _error("validation", "Provide either an email address or a phone number.")

    customer = _find_customer(email, phone)
    if customer is None:
        return _error("validation", "No customer found with that email or phone number. Ask the customer to double-check it.")
    return customer


def lookup_order_status(order_id):
    order = ORDERS.get(order_id)  # .get() returns None instead of crashing if missing
    if order is None:
        # validation: the ID points at nothing, so retrying the same ID can't help.
        return _error("validation", f"No order found with ID {order_id}. Ask the customer to check the ID.")

    # Return only what the tool description promised: status, carrier,
    # tracking number, and estimated delivery. Don't hand Claude more than it needs.
    return {
        "order_id": order["order_id"],
        "status": order["status"],
        "carrier": order["carrier"],
        "tracking_number": order["tracking_number"],
        "estimated_ship_date": order["estimated_ship_date"],
        "actual_ship_date": order["actual_ship_date"],
        "notes": order["notes"],
    }


def cancel_order(order_id, reason="other"):
    order = ORDERS.get(order_id)
    if order is None:
        return _error("validation", f"No order found with ID {order_id}. Ask the customer to check the ID.")

    # Business rule from the tool description: only orders that haven't shipped.
    # The rule lives in OUR code, so we don't depend on Claude to enforce it.
    if order["status"] != "processing":
        # business: the ID is fine, but the cancellation policy says no.
        return _error(
            "business",
            f"Order {order_id} cannot be cancelled because its status is "
            f"'{order['status']}'. Only orders still processing can be cancelled. "
            "If it was already shipped or delivered, a refund may be possible instead."
        )

    # NOTE: this is a mock, so we don't change mock_data. A real version would
    # update the order's status in the database here.
    return {"order_id": order_id, "cancelled": True, "reason": reason}


def order_total_cents(order):
    # Prices in mock_data are in dollars (79.99). Our tools use cents (7999) because
    # money as whole numbers avoids rounding bugs. round() fixes float quirks like 79.99*100.
    return sum(round(item["price"] * 100) * item["quantity"] for item in order["items"])


def _money_back_amount(order_id, amount_cents, what):
    """The rules shared by refunds and store credit. Returns (amount_cents, error).

    what: the word for error messages, 'Refund' or 'Store credit'.
    """
    order = ORDERS.get(order_id)
    if order is None:
        return None, _error("validation", f"No order found with ID {order_id}. Ask the customer to check the ID.")

    # Business rule: money goes back only for orders that were already charged and sent.
    if order["status"] not in ("shipped", "delivered"):
        return None, _error(
            "business",
            f"Order {order_id} has status '{order['status']}' and has not shipped. "
            "Use cancel_order instead.",
        )

    total_cents = order_total_cents(order)

    # No amount given means "the whole order".
    if amount_cents is None:
        amount_cents = total_cents
    if amount_cents <= 0:
        return None, _error("validation", f"{what} amount must be greater than zero.")
    if amount_cents > total_cents:
        # business: a well-formed amount that breaks the rule.
        return None, _error(
            "business",
            f"{what} of {amount_cents} cents is more than the order total of "
            f"{total_cents} cents.",
        )
    return amount_cents, None


def issue_refund(order_id, reason, amount_cents=None):
    amount_cents, error = _money_back_amount(order_id, amount_cents, "Refund")
    if error:
        return error

    global _refund_counter  # we are changing a variable defined outside this function
    _refund_counter += 1
    return {
        "refund_id": f"REF-{_refund_counter}",
        "order_id": order_id,
        "amount_cents": amount_cents,
        "reason": reason,
        "expected_by": _future_date(5),
    }


def apply_store_credit(order_id, reason, amount_cents=None):
    amount_cents, error = _money_back_amount(order_id, amount_cents, "Store credit")
    if error:
        return error

    global _credit_counter
    _credit_counter += 1
    return {
        "credit_id": f"CR-{_credit_counter}",
        "order_id": order_id,
        "amount_cents": amount_cents,
        "reason": reason,
    }


def search_orders(status=None, keyword=None, session=None):
    # Only the VERIFIED customer's orders are ever searched. The gate has already
    # confirmed someone is verified, and we read who from the session, not from Claude.
    verified_id = session["verified_customer_id"]
    matches = []
    for order in ORDERS.values():
        if order["customer_id"] != verified_id:
            continue
        if status and order["status"] != status:
            continue
        products = [item["product"] for item in order["items"]]
        if keyword and not any(keyword.lower() in p.lower() for p in products):
            continue
        matches.append({"order_id": order["order_id"], "status": order["status"], "items": products})
    # No matches is a valid, successful answer ("searched, found nothing"), not an error.
    return {"orders": matches[:10], "count": len(matches[:10])}


def update_shipping_address(order_id, street, city, state, postal_code):
    order = ORDERS.get(order_id)
    if order is None:
        return _error("validation", f"No order found with ID {order_id}. Ask the customer to check the ID.")
    if not all(v and v.strip() for v in (street, city, state, postal_code)):
        return _error("validation", "Street, city, state, and postal code are all required.")
    if order["status"] != "processing":
        # business: once it ships, the address can't change.
        return _error(
            "business",
            f"Order {order_id} has status '{order['status']}', so its address can no longer be changed. "
            "Only orders still processing can be redirected.",
        )
    # MOCK: a real version would save the new address on the order.
    return {
        "order_id": order_id,
        "updated": True,
        "shipping_address": {"street": street, "city": city, "state": state, "postal_code": postal_code},
    }


# A tiny fake help center. A real one would be a search service.
HELP_ARTICLES = [
    {
        "title": "Return Policy",
        "summary": "Items can be returned within 30 days of delivery in original condition.",
        "url": "https://help.example.com/returns",
    },
    {
        "title": "Shipping Times",
        "summary": "Standard shipping takes 3-5 business days. Express takes 1-2.",
        "url": "https://help.example.com/shipping",
    },
    {
        "title": "Cancelling an Order",
        "summary": "Orders can be cancelled until they ship. After that, request a return.",
        "url": "https://help.example.com/cancel",
    },
]


def search_help_articles(query):
    # Very simple keyword search: an article matches if any word from the query
    # appears in its title or summary. Real search would rank by relevance.
    words = query.lower().split()
    matches = [
        article
        for article in HELP_ARTICLES
        if any(w in (article["title"] + " " + article["summary"]).lower() for w in words)
    ]
    return {"articles": matches[:5]}  # the tool description promises up to 5


def create_support_ticket(customer_id, subject, details, order_id=None, ticket_type="problem"):
    if customer_id not in CUSTOMERS:
        return _error("validation", f"No customer found with ID {customer_id}.")

    global _ticket_counter
    _ticket_counter += 1
    return {
        "ticket_id": f"TKT-{_ticket_counter}",
        "ticket_type": ticket_type,
        "customer_id": customer_id,
        "subject": subject,
        "order_id": order_id,
        "expected_response_by": _future_date(2),
    }


def build_handoff(session, reason, summary, customer_wants="", suggested_next_step="", automatic=False):
    """The structured handoff a human receives (exam task 1.4).

    Code supplies the FACTS: who is verified, what was done, which agents were involved.
    Claude supplies the JUDGMENT: the summary, what the customer wants, a suggested next step.
    Facts come from the session, never from Claude, so a wrong ID in Claude's message can't mislead the human.
    """
    global _handoff_counter
    _handoff_counter += 1
    customer_id = session["verified_customer_id"]
    customer = CUSTOMERS.get(customer_id) if customer_id else None
    record = {
        "handoff_id": f"HO-{_handoff_counter}",
        "automatic": automatic,  # True when a hook escalated, not Claude
        "reason": reason,
        "customer": {
            "verified": customer is not None,
            "customer_id": customer_id,
            "name": customer["name"] if customer else None,
        },
        "summary": summary,
        "customer_wants": customer_wants,
        "suggested_next_step": suggested_next_step,
        "actions_taken": list(session["actions"]),
        "agents_involved": [session["active_agent"]] if not session["transfers"]
        else [t["to"] for t in session["transfers"]],
    }
    session["escalations"].append(record)
    return record


def escalate_to_human(reason, summary, customer_wants="", suggested_next_step="", customer_id=None, session=None):
    # customer_id is accepted but ignored: the code knows who is verified, so Claude's guess is never used.
    record = build_handoff(session, reason, summary, customer_wants, suggested_next_step)
    # Claude only needs to know it worked. The full record goes to the human, not back into the chat.
    return {
        "escalated": True,
        "handoff_id": record["handoff_id"],
        "estimated_wait_minutes": 5,
        "message": "A human agent has the full case summary. Tell the customer someone will pick this up shortly.",
    }


def transfer_to_agent(agent, reason, session=None):
    # The SESSION says who is active. Changing it here is the whole handoff: the loop reads
    # session["active_agent"] on every call, and the verified customer stays in the same session.
    if agent not in AGENTS:
        return _error("validation", f"There is no agent named {agent}. Choose one of: {', '.join(AGENTS)}.")
    if agent == session["active_agent"]:
        return _error("validation", f"You are already the {agent} agent. Handle this yourself or choose a different agent.")
    session["active_agent"] = agent
    session["transfers"].append({"to": agent, "reason": reason})
    return {
        "transferred": True,
        "agent": agent,
        "verified": session["verified_customer_id"] is not None,
        # Read by BOTH sides: in our own loop the new agent reads it next; with the Agent SDK the old agent
        # reads it, finishes its turn, and the new agent starts on the next turn.
        "message": (
            f"Handoff recorded: the {agent} agent ({AGENTS[agent]['description']}) now has this customer. "
            f"If you are the {agent} agent, carry on with the customer's request: {reason} "
            f"If you were the previous agent, tell the customer briefly that you have passed them on, and stop."
        ),
    }


# ---------------------------------------------------------------------------
# The dispatcher: the one function the agent loop will call.
# ---------------------------------------------------------------------------

# Maps the tool NAME (the string Claude sends back) to the Python function.
# The keys must match the "name" in tools.py exactly.
TOOL_FUNCTIONS = {
    "send_verification_code": send_verification_code,
    "verify_identity": verify_identity,
    "lookup_customer": lookup_customer,
    "lookup_order_status": lookup_order_status,
    "search_orders": search_orders,
    "update_shipping_address": update_shipping_address,
    "cancel_order": cancel_order,
    "issue_refund": issue_refund,
    "apply_store_credit": apply_store_credit,
    "search_help_articles": search_help_articles,
    "create_support_ticket": create_support_ticket,
    "escalate_to_human": escalate_to_human,
    "transfer_to_agent": transfer_to_agent,
}


# Tools that touch an order, and the customer record. These are LOCKED until the
# customer has proven who they are with a code (send_verification_code + verify_identity).
ORDER_TOOLS = {
    "lookup_order_status",
    "search_orders",
    "update_shipping_address",
    "cancel_order",
    "issue_refund",
    "apply_store_credit",
}
GATED_TOOLS = ORDER_TOOLS | {"lookup_customer", "create_support_ticket"}

# Tools that need to read or change THIS conversation's session. The code hands the
# session in; Claude never sees it or supplies it.
SESSION_TOOLS = {"send_verification_code", "verify_identity", "search_orders", "transfer_to_agent", "escalate_to_human"}


def new_session():
    """Fresh per-conversation memory. Nobody is verified until verify_identity succeeds.

    ONE session follows the whole conversation, across agent switches (task 1.4):
      verified_customer_id - who proved themselves, written only by verify_identity
      pending_verification - a code waiting to be confirmed
      active_agent         - which agent is talking now (None until the loop starts)
      transfers            - every handoff between agents
      escalations          - every handoff to a human (made by Claude or by a hook)
      outbox               - the fake messages "sent" to the customer (the test UI shows them as an inbox)
      actions              - log of tool calls and how each ended; goes into any handoff to a human
      permission_denials   - how many times a tool said "not yours"; hooks.py escalates on repeats
    """
    return {
        "verified_customer_id": None,
        "pending_verification": None,
        "active_agent": None,
        "transfers": [],
        "escalations": [],
        "outbox": [],
        "actions": [],
        "permission_denials": 0,
    }


def _check_access(tool_name, tool_input, session):
    """The gate (exam task 1.4). Returns an error dict to block the call, or None to allow it.

    This is CODE, so Claude cannot talk its way past it, no matter what it was told.
    """
    if tool_name not in GATED_TOOLS:
        return None

    verified_id = session["verified_customer_id"]
    if verified_id is None:
        # validation: the call can't run yet. Retrying the SAME call won't help,
        # but verifying first will, so the message says how.
        return _error(
            "validation",
            "The customer has not been verified yet. Verification is done by the customer_service agent: "
            "if you have send_verification_code, use it with their email or phone, ask for the code, "
            "then call verify_identity and try again. If you do not have those tools, call "
            "transfer_to_agent to customer_service so they can verify; the verification carries over.",
        )

    if tool_name == "lookup_customer":
        # A verified customer may only read THEIR OWN record, never someone else's.
        found = _find_customer(tool_input.get("email"), tool_input.get("phone"))
        if found is not None and found["customer_id"] != verified_id:
            return _error(
                "permission",
                "That email or phone number is not on the verified customer's account, "
                "so the record can't be shown.",
            )
        return None

    if tool_name == "create_support_ticket" and tool_input.get("customer_id") != verified_id:
        # permission: a ticket may only be filed for the customer who proved who they are.
        return _error(
            "permission",
            "A ticket can only be created for the verified customer. Use the customer ID of the "
            "person you verified in this conversation.",
        )

    order = ORDERS.get(tool_input.get("order_id"))
    if order is not None and order["customer_id"] != verified_id:
        # permission: the person is verified, but this order is not theirs.
        # We don't say whose order it is.
        return _error(
            "permission",
            "That order is not on the verified customer's account, so it can't be "
            "accessed. Ask the customer to double-check the order number.",
        )

    return None  # allowed (a missing order falls through to the tool's own "not found")


def run_tool(tool_name, tool_input, session=None):
    """Run the tool Claude asked for. Returns (text, is_error).

    tool_name:  the "name" from Claude's tool_use block, e.g. 'lookup_order_status'
    tool_input: the "input" dict from that block, e.g. {'order_id': 'ORD-8821'}
    session:    this conversation's memory (see new_session). If you pass none,
                nobody is verified, which is the safe default.

    text:     the result as a JSON string (a tool_result's content has to be text)
    is_error: True when the call failed. The agent passes this to the API as
              "is_error": true so Claude knows the whole call failed.
    """
    if session is None:
        session = new_session()

    # Customers type ' ord-8821 '. Clean the ID once, here, BEFORE the gate and the tool see it,
    # so 'ord-8821' and 'ORD-8821' are the same order everywhere.
    if isinstance(tool_input.get("order_id"), str):
        tool_input = {**tool_input, "order_id": tool_input["order_id"].strip().upper()}

    function = TOOL_FUNCTIONS.get(tool_name)
    blocked = _check_access(tool_name, tool_input, session)
    if function is None:
        # Claude asked for a tool we haven't built. Tell it so it can recover.
        result = _error("validation", f"Unknown tool: {tool_name}")
    elif blocked is not None:
        result = blocked  # the gate said no, so the tool never runs
    else:
        try:
            _maybe_fail(tool_name)  # test hook; does nothing unless a failure was set up
            # **tool_input unpacks the dict into named arguments:
            # {'order_id': 'X'} becomes lookup_order_status(order_id='X')
            if tool_name in SESSION_TOOLS:
                result = function(**tool_input, session=session)
            else:
                result = function(**tool_input)
        except TimeoutError:
            # A real database or API call that times out lands here.
            result = _error("transient", f"{tool_name} timed out. Trying the same call again may work.")
        except TypeError as e:
            # Wrong or missing arguments (for example, a required input was left out).
            result = _error("validation", f"Bad inputs for {tool_name}: {e}")
        except Exception as e:
            # Anything unexpected. We can't be sure, so we treat it as temporary.
            result = _error("transient", f"{tool_name} failed unexpectedly: {e}")

    return json.dumps(result), "errorCategory" in result
