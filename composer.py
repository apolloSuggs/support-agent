"""composer.py — a small chat page for testing the support agents by typing as the customer.

Run:   .venv/bin/python composer.py      then open  http://127.0.0.1:8000

What it is: a thin web front for coordinator.py (a coordinator that starts subagents) or sdk_agent.py
(agents that hand the customer on). Pick the design with the dropdown at the top. You type in the composer at the bottom, the Agent SDK
agents answer, and the side panel shows what the CUSTOMER cannot see: which agent is active, who is
verified, tool calls, handoffs to a human. The "inbox" is where the fake verification code arrives,
so you can type it back in, as a real customer would.

It listens only on your own machine (127.0.0.1) because every message costs API money and there is no login.
"""

import asyncio
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from mock_data import CUSTOMERS
from coordinator import CoordinatorConversation
from sdk_agent import Conversation

PAGE = Path(__file__).with_name("composer.html")
lock = asyncio.Lock()  # one message at a time: a conversation is a sequence
MODES = {"coordinator": CoordinatorConversation, "handoff": Conversation}
mode = "coordinator"                 # the design being tested: a coordinator with subagents, or agents handing off
conversation = CoordinatorConversation()


def state():
    session = conversation.session
    customer = CUSTOMERS.get(session["verified_customer_id"]) if session["verified_customer_id"] else None
    return {
        "conversation_id": conversation.id,
        "mode": mode,
        "agent": "coordinator" if mode == "coordinator" else session["active_agent"],
        "verified": {"customer_id": customer["customer_id"], "name": customer["name"]} if customer else None,
        "inbox": session["outbox"],
        "escalations": session["escalations"],
        "transfers": len(session["transfers"]),
    }


async def home(request):
    return HTMLResponse(PAGE.read_text())


async def get_state(request):
    return JSONResponse(state())


async def message(request):
    body = await request.json()
    text = (body.get("message") or "").strip()
    if not text:
        return JSONResponse({"error": "Type a message first."}, status_code=400)
    async with lock:
        try:
            events = await conversation.send(text)
        except Exception as error:  # show the problem in the page instead of a blank screen
            return JSONResponse({"error": f"{type(error).__name__}: {error}", "state": state()}, status_code=500)
    return JSONResponse({"events": events, "state": state()})


async def reset(request):
    global conversation, mode
    body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    async with lock:
        mode = body.get("mode") if body.get("mode") in MODES else mode
        conversation = MODES[mode]()
    return JSONResponse({"state": state()})


app = Starlette(routes=[
    Route("/", home),
    Route("/api/state", get_state),
    Route("/api/message", message, methods=["POST"]),
    Route("/api/reset", reset, methods=["POST"]),
])

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
    # port 8000 busy? change it here and in the URL above.
