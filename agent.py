"""The support agents: an agentic loop (exam task 1.1) with scoped tools (task 2.3).

The loop in plain English:
  1. Send the whole conversation to Claude.
  2. If Claude's stop_reason is "tool_use", run the tool(s) it asked for,
     add the results to the conversation, and go back to step 1.
  3. If stop_reason is "end_turn", Claude is finished with this turn. Stop.

Which agent runs (customer_service, order_processing, refund_processing) decides
two things: its instructions and the only tools Claude is shown. See agents.py.

Run a chat:   .venv/bin/python agent.py
              .venv/bin/python agent.py "I want a refund for ORD-8821"
Test a backup gate by skipping the front door:
              .venv/bin/python agent.py --start-at refund_processing "I want a refund"
"""

import json
import sys

import anthropic
from dotenv import load_dotenv

from agents import AGENTS, ENTRY_AGENT
from hooks import call_tool
from tool_runner import new_session
from tools import tools_for

load_dotenv()  # reads ANTHROPIC_API_KEY from .env (never printed)
client = anthropic.Anthropic()

MODEL = "claude-haiku-4-5-20251001"
MAX_PASSES = 10  # backup limit on tool rounds, in case the loop never ends


def call_claude(messages, agent):
    # The API is stateless: we send the FULL history every time. We also send only
    # THIS agent's tools, so Claude cannot choose a tool outside its role.
    return client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=agent["system_prompt"],
        tools=tools_for(agent["tools"]),
        messages=messages,
    )


def run_agent(customer_message, messages=None, session=None, start_at=None):
    """Handle one customer message. Pass the same messages and session back in to continue a chat.

    Every new conversation starts at the front door (ENTRY_AGENT). Only tests pass start_at,
    to put a conversation somewhere else on purpose and check that the backup gates hold.
    If a transfer_to_agent call changes session["active_agent"], the loop switches agents and
    keeps the same history and session.
    """
    if messages is None:
        messages = []
    if session is None:
        # Created fresh for EVERY conversation, so one customer's verification
        # can never carry over to the next customer.
        session = new_session()
    if session["active_agent"] is None:
        session["active_agent"] = start_at or ENTRY_AGENT
    agent = AGENTS[session["active_agent"]]

    messages.append({"role": "user", "content": customer_message})
    response = call_claude(messages, agent)
    passes = 0

    # The loop continues ONLY while Claude is asking for a tool.
    # We never decide "done" by reading Claude's text.
    # MAX_PASSES is just a safety net against a runaway loop, not the normal way to stop.
    while response.stop_reason == "tool_use" and passes < MAX_PASSES:
        passes += 1
        # 1. Append Claude's reply (it contains the tool_use blocks).
        messages.append({"role": "assistant", "content": response.content})

        # 2. Run every tool Claude asked for and collect the results.
        tool_results = []
        for block in response.content:
            if block.type == "text":
                print(f"\n[Claude says] {block.text}")
            elif block.type == "tool_use":
                print(f"\n[Tool call]   {block.name}({block.input})")
                # Hooks wrap the call: scope check and refund limit before, auto-escalation after.
                seen = len(session["escalations"])
                result, is_error = call_tool(session["active_agent"], block.name, block.input, session)
                for record in session["escalations"][seen:]:
                    # This is what the HUMAN receives. Claude only sees a short confirmation.
                    print(f"\n[Handoff to human] {json.dumps(record, indent=2)}")
                print(f"[Tool {'ERROR' if is_error else 'result'}] {result}")
                tool_result = {
                    "type": "tool_result",
                    "tool_use_id": block.id,  # matches this result to Claude's request
                    "content": result,
                }
                if is_error:
                    tool_result["is_error"] = True  # tells Claude the whole call failed
                tool_results.append(tool_result)

        # 3. Tool results go back as a USER message.
        messages.append({"role": "user", "content": tool_results})

        # 4. If a transfer happened, the NEXT call uses the new agent's prompt and tools.
        if AGENTS[session["active_agent"]] is not agent:
            agent = AGENTS[session["active_agent"]]
            print(f"\n[Transfer] now talking to: {session['active_agent']}")

        # 5. Call Claude again with the full history.
        response = call_claude(messages, agent)

    # Loop ended. Add Claude's last reply so the history is complete.
    messages.append({"role": "assistant", "content": response.content})

    if response.stop_reason == "tool_use":
        print(f"\n[Warning] Safety cap hit: stopped after {MAX_PASSES} passes while Claude still wanted a tool.")
    elif response.stop_reason != "end_turn":
        # e.g. "max_tokens": the loop stopped for a reason other than finishing.
        print(f"\n[Warning] Stopped with stop_reason={response.stop_reason!r}, not 'end_turn'.")

    final_text = "".join(b.text for b in response.content if b.type == "text")
    print(f"\n[Final reply] {final_text}")
    return messages


if __name__ == "__main__":
    args = sys.argv[1:]
    start_at = None
    if len(args) >= 2 and args[0] == "--start-at" and args[1] in AGENTS:
        start_at = args[1]  # testing only: skip the front door to try the backup gates
        args = args[2:]
    print("You are chatting with support. Type your messages as the customer. Press Enter on an empty line to quit.")

    history, session = [], new_session()
    message = " ".join(args) or input("\nYou: ")
    while message.strip():
        history = run_agent(message, history, session, start_at)
        message = input("\nYou: ")
