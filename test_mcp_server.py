"""Test the MCP server the way a real client would: start it as a program and talk to it.

Free (no API calls). Run:  .venv/bin/python test_mcp_server.py
"""

import json
import os
import re
import sys

import anyio
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

import session_store
from tools import TOOLS

failures = 0


def check(ok, label):
    global failures
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        failures += 1


def result_json(result):
    return json.loads(result.content[0].text)


async def run():
    params = StdioServerParameters(command=sys.executable, args=["mcp_server.py"])
    async with Client(params) as client:
        listed = await client.list_tools()
        names = {t.name for t in listed.tools}
        check(names == {t["name"] for t in TOOLS}, f"server lists all {len(TOOLS)} tools from tools.py")
        issue = next(t for t in listed.tools if t.name == "issue_refund")
        check("order_id" in issue.input_schema["properties"], "input schema comes through (issue_refund has order_id)")
        check(issue.description.startswith(next(t for t in TOOLS if t["name"] == "issue_refund")["description"][:40]),
              "descriptions come through unchanged")

        # The gate lives in the server: no verification, no order access.
        r = await client.call_tool("lookup_order_status", {"order_id": "ORD-8821"})
        check(r.is_error and result_json(r)["errorCategory"] == "validation", "unverified order lookup is blocked by the server's gate")

        # Real verification flow. The code is never in a result (Claude must not see it), so this test cannot
        # read it either. A wrong code fails properly, and the lock escalates through the hooks.
        r = await client.call_tool("send_verification_code", {"email": "sarah.chen@email.com"})
        check(not r.is_error and not re.search(r"\d{6}", json.dumps(result_json(r))), "no 6-digit code appears in the result")
        for _ in range(3):
            r = await client.call_tool("verify_identity", {"code": "000000", "email": "sarah.chen@email.com"})
        check(r.is_error and "handoff" in result_json(r), "3 wrong codes lock verification and the hook escalates (hooks run in the server)")

        r = await client.call_tool("search_help_articles", {"query": "return"})
        check(not r.is_error and result_json(r)["articles"], "an ungated tool works")

    # Session survives NEW server processes when SESSION_ID is set (the Agent SDK client starts one per turn).
    cid = "test-persist"
    session_store.save(cid, session_store.load("does-not-exist"))
    def conn():
        return Client(StdioServerParameters(command=sys.executable, args=["mcp_server.py"], env={**os.environ, "SESSION_ID": cid}))
    async with conn() as c1:
        await c1.call_tool("send_verification_code", {"email": "sarah.chen@email.com"})
    code = session_store.load(cid)["pending_verification"]["code"]  # the TEST plays the customer reading their inbox
    check(session_store.load(cid)["outbox"][0]["to"] == "sarah.chen@email.com", "the fake message lands in the session's outbox")
    async with conn() as c2:
        r = await c2.call_tool("verify_identity", {"code": code, "email": "sarah.chen@email.com"})
        check(not r.is_error and result_json(r)["verified"], "a second server process accepts the code from the first")
    async with conn() as c3:
        r = await c3.call_tool("lookup_order_status", {"order_id": "ORD-8821"})
        check(not r.is_error, "a third process is still verified and can read the order")
    session_store._path(cid).unlink()

    print(f"\n{'All passed.' if not failures else f'{failures} FAILED.'}")


anyio.run(run)
sys.exit(1 if failures else 0)
