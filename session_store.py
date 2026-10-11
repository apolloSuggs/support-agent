"""session_store.py — keeps each conversation's session OUTSIDE any one process.

Why: with the Agent SDK a turn can start a fresh server process, and a handoff changes the agent.
If "who is verified" lived only in memory, it would vanish. Real systems keep this in a database or
Redis, keyed by a conversation ID. We use one small JSON file per conversation in .sessions/.

The session still holds only what CODE wrote (verified customer, pending code, handoffs). Claude never
reads or writes this file.
"""

import json
import os
from pathlib import Path

from tool_runner import new_session

DIR = Path(__file__).parent / ".sessions"


def _path(conversation_id):
    safe = "".join(ch for ch in conversation_id if ch.isalnum() or ch in "-_")
    return DIR / f"{safe}.json"


def load(conversation_id):
    path = _path(conversation_id)
    return json.loads(path.read_text()) if path.exists() else new_session()


def save(conversation_id, session):
    DIR.mkdir(exist_ok=True)
    path = _path(conversation_id)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(session))
    os.replace(temp, path)  # swap in one step so a reader never sees a half-written file
