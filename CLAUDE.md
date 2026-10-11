# Support Agent — Learning Project

This is a **learning project** for the Claude Certified Architect course (Dev Compass). It is required work for the certification, so the goal is for the user to understand every step, not just to get working code.

## Certification context

The exam is **Claude Certified Architect – Foundations** (code CCAR-F): 60 scenario-based questions in 120 minutes, passing score 720/1,000. It tests judgment about tradeoffs, not memorized facts. The official guide is `Claude Certified Architech Guide.pdf` in this folder.

| # | Domain | Weight | Study file |
|---|---|---|---|
| 1 | Agentic Architecture & Orchestration | 27% | `certification/domain-1-agentic-architecture/STUDY.md` |
| 2 | Tool Design & MCP Integration | 18% | `certification/domain-2-tool-design-mcp/STUDY.md` |
| 3 | Claude Code Configuration & Workflows | 20% | `certification/domain-3-claude-code-config/STUDY.md` |
| 4 | Prompt Engineering & Structured Output | 20% | `certification/domain-4-prompts-structured-output/STUDY.md` |
| 5 | Context Management & Reliability | 15% | `certification/domain-5-context-reliability/STUDY.md` |

This support agent is the exam's **Scenario 1** (customer support resolution agent).

**How to use these files**
- Before building anything for a domain, read that domain's `STUDY.md` and tell the user which task statement (like 1.1 or 2.2) the step covers.
- The user is a vibe coder who wants to understand the theory and to recognize correct code. Each `STUDY.md` has a "red flags when reviewing AI-written code" section. Use it to explain what correct code looks like and what to watch for.
- Keep build notes and code for a domain in its own folder. Update the checklists and the progress tracker in `certification/README.md` as tasks are completed.
- Lesson routine for every task (course lessons, learn, brief, build, quiz, record): `certification/LESSON-PLAN.md`. Follow it one task at a time.
- The user also takes the Dev Compass course. `certification/COURSE-CROSSWALK.md` lists which course lessons feed each task. Ask what they finished before starting a task. My own summary notes of each lesson live in `certification/course-notes/`: read the matching note before working on a task, and capture a note when the user opens a new lesson (lessons unlock one at a time, never try to read locked ones). Paraphrase, never copy course text, never record quiz answers.
- Study hub: `certification/README.md`. The notes are paraphrased from the guide, so link to the PDF for original wording and do not copy exam content verbatim.

## How to work in this project

- Go **step by step**. Do one lesson-sized step at a time and don't build ahead of the lesson.
- **Explain what and why** for each step, in plain English, and name the SDK/API concept it teaches (tool use, the agentic loop, `stop_reason`, messages, etc.).
- Be clear and direct. If something is unknown or unverified, say so.
- Ask before doing things the lesson expects the user to do themselves, and offer to do mechanical work (moving files, setup).
- Keep code simple and readable, with short comments on the parts that teach something.
- **Guide first.** When our build differs from the course or from what the exam guide expects (a different style, name, or file), say so while building, and put a "guide vs ours" box on the matching lesson page, so the user never learns a different style by accident. Define every acronym and new term when first used.

## Project setup

- Python 3.12 virtual environment at `.venv/`. Run code with `.venv/bin/python` (or activate the venv).
- Packages: `anthropic`, `python-dotenv`, `claude-agent-sdk`, `mcp[cli]` (2.x; `FastMCP` is now `MCPServer`), and `cryptography<46` (newer versions fail to load on this Mac: missing OpenSSL symbol).
- API key lives in `.env` at the project root as `ANTHROPIC_API_KEY`. **Never print, log, or read out its value.** `.env` is in `.gitignore`.
- Dates use `MM-DD-YYYY`.

## Files

- `tools.py` — tool definitions for the support agent (`TOOLS` list).
- `agent.py` — the agentic loop and a chat runner (`python agent.py`; every chat starts at the customer_service front door, `--start-at <agent>` is for testing the backup gates).
- `agents.py` — the three agents (customer_service, order_processing, refund_processing): a prompt and a tool list each. One shared session; agents pass the customer on with `transfer_to_agent`.
- `sdk_agent.py` — the same agents run by the Claude Agent SDK, using the MCP server (`python sdk_agent.py`). `test_sdk_agent.py` checks it (`--live` runs Claude).
- `coordinator.py` — hub-and-spoke version on the Agent SDK: one coordinator verifies the customer and starts order_specialist and refund_specialist and gets a structured report from each, built in code from the real tool results (`python coordinator.py`). `test_coordinator.py` checks it (`--live` runs Claude).
- `composer.py` + `composer.html` — a local chat page for typing as the customer (dropdown picks the coordinator design or the handoff design), with a side panel of what is happening behind the scenes (`python composer.py`, open http://127.0.0.1:8000). Uses the SDK path.
- `session_store.py` — keeps each conversation's session in `.sessions/` so it survives new server processes.
- `mcp_server.py` — our 13 tools behind an MCP server (stdio). Gate and hooks run inside it. `.mcp.json` registers it for Claude Code.
- `test_mcp_server.py` — starts the server as a client would and checks it (free, no API calls).
- `hooks.py` — before/after hooks around every tool call (scope check, refund limit, auto-escalation).
- `tool_runner.py` — the functions that execute each tool, the verification gate, and the `run_tool()` dispatcher.
- `test_errors.py` — offline checks for errors, the gate, verification and agent scopes (`--live` adds Claude runs).
- `mock_data.py` — fake customers and orders the tools read from.
- `test_api.py` — first API call, to confirm the key works.
- `certification/SAMPLE-QUESTIONS.md` — the 12 sample questions in the exam guide (section 9) and which are ready to practise.
- `certification/` — study notes and hands-on build notes, one folder per exam domain.
- `.claude/skills/new-lesson/SKILL.md` — the routine to run unprompted whenever a course lesson arrives (note, build alongside, lesson page, quiz, records).
- `.claude/skills/tool-definitions/SKILL.md` — the standard every tool definition must follow: clear, unique descriptions so Claude can always tell which tool is for which action.
