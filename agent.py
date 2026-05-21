"""
RamBabu agent — LangGraph (default) or CrewAI, with MCP tools from selected integrations.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from helper import HUB_ID, init_hub, run_tool
from mcp_hub import mcp
from servers import EXTERNAL_SERVERS
from studio_log import log

load_dotenv()

MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/owl-alpha")
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
ASSISTANT_NAME = "RamBabu"
ASSISTANT_INITIALS = "RB"
MAX_TOOLS_FOR_LLM = 80

_sessions: dict[str, dict[str, Any]] = {}
_memory = MemorySaver()
_tool_catalogs: dict[str, str] = {}


def _env_ready(env_keys: list) -> bool:
    return all(os.getenv(k) for k in env_keys) if env_keys else True


def list_frameworks() -> list[dict]:
    return [
        {
            "id": "langgraph",
            "title": "LangGraph",
            "description": "Graph agent with tool loop (recommended)",
            "available": True,
            "default": True,
        },
        {
            "id": "crewai",
            "title": "CrewAI",
            "description": "Crew-based task agent",
            "available": True,
            "default": False,
        },
    ]


def list_integrations() -> list[dict]:
    init_hub()
    rows = [
        {
            "id": HUB_ID,
            "title": "Hub (local)",
            "description": "Local ping / echo tools",
            "env_ready": True,
            "default_on": True,
        }
    ]
    for s in EXTERNAL_SERVERS:
        env_keys = s.get("env_keys", [])
        rows.append(
            {
                "id": s["namespace"],
                "title": s.get("title") or s["namespace"],
                "description": s.get("package") or s.get("url", ""),
                "env_ready": _env_ready(env_keys),
                "env_keys": env_keys,
                "default_on": False,
            }
        )
    return rows


def _tool_allowed(name: str, integrations: list[str]) -> bool:
    is_external = any(name.startswith(s["namespace"] + "_") for s in EXTERNAL_SERVERS)
    if not is_external:
        return HUB_ID in integrations
    for ns in integrations:
        if ns != HUB_ID and name.startswith(ns + "_"):
            return True
    return False


async def _picked_mcp_tools(integrations: list[str]):
    all_tools = await mcp.list_tools()
    picked = [t for t in all_tools if _tool_allowed(t.name, integrations)]
    return picked[:MAX_TOOLS_FOR_LLM]


async def _tools_catalog(integrations: list[str]) -> str:
    key = ",".join(sorted(integrations))
    if key in _tool_catalogs:
        return _tool_catalogs[key]
    lines = []
    for t in await _picked_mcp_tools(integrations):
        desc = (t.description or "")[:120].replace("\n", " ")
        lines.append(f"- {t.name}: {desc}")
    catalog = "\n".join(lines) if lines else "(no tools)"
    _tool_catalogs[key] = catalog
    return catalog


def _llm():
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("Set OPENROUTER_API_KEY in .env")
    return ChatOpenAI(
        model=MODEL,
        api_key=api_key,
        base_url=OPENROUTER_BASE,
        temperature=0.3,
    )


async def _mcp_call(tool_name: str, arguments_json: str = "{}", tool_log: list | None = None) -> str:
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError as e:
        return f"Invalid JSON arguments: {e}"
    if not isinstance(args, dict):
        return "arguments_json must be a JSON object"

    log.info("agent mcp_call %s %s", tool_name, args)
    result = await run_tool(tool_name, args)
    if tool_log is not None:
        tool_log.append({"tool": tool_name, "ok": result.get("ok", False)})

    if result.get("ok"):
        return result.get("result") or "(empty)"
    err = result.get("error", "tool failed")
    if result.get("hint"):
        err += "\nHint: " + result["hint"]
    return err


async def _langchain_mcp_tool(tool_log: list) -> StructuredTool:
    async def _run(tool_name: str, arguments_json: str = "{}") -> str:
        return await _mcp_call(tool_name, arguments_json, tool_log)

    return StructuredTool.from_function(
        coroutine=_run,
        name="mcp_call",
        description=(
            "Call an MCP tool by exact name. arguments_json is a JSON object string "
            "matching the tool schema (e.g. {\"operation\":\"search\",\"email\":\"...\"})."
        ),
    )


def create_session(integrations: list[str], framework: str = "langgraph") -> dict:
    if not integrations:
        integrations = [HUB_ID]
    if framework not in ("langgraph", "crewai"):
        framework = "langgraph"

    session_id = str(uuid.uuid4())[:8]
    _sessions[session_id] = {
        "id": session_id,
        "integrations": integrations,
        "framework": framework,
        "started": False,
    }
    return {
        "session_id": session_id,
        "integrations": integrations,
        "framework": framework,
        "assistant": ASSISTANT_NAME,
    }


def get_session(session_id: str) -> dict | None:
    return _sessions.get(session_id)


async def _chat_langgraph(session: dict, user_message: str) -> dict:
    tool_log = []
    catalog = await _tools_catalog(session["integrations"])
    graph = create_react_agent(
        _llm(),
        [await _langchain_mcp_tool(tool_log)],
        checkpointer=_memory,
    )
    config = {"configurable": {"thread_id": session["id"]}}

    messages = [HumanMessage(content=user_message)]
    if not session.get("started"):
        messages.insert(
            0,
            SystemMessage(
                content=(
                    f"You are {ASSISTANT_NAME}, a helpful personal assistant.\n"
                    f"Integrations: {', '.join(session['integrations'])}.\n"
                    "Use mcp_call(tool_name, arguments_json) to run tools.\n"
                    f"Available tools:\n{catalog}"
                )
            ),
        )
        session["started"] = True

    result = await graph.ainvoke({"messages": messages}, config)
    reply = ""
    for m in reversed(result.get("messages", [])):
        if isinstance(m, AIMessage) and m.content:
            reply = m.content if isinstance(m.content, str) else str(m.content)
            break

    return {
        "ok": True,
        "reply": reply,
        "tool_calls_used": tool_log,
        "framework": "langgraph",
        "integrations": session["integrations"],
    }


async def _chat_crewai(session: dict, user_message: str) -> dict:
    from crewai import Agent, Crew, LLM, Task
    from crewai.tools import tool

    tool_log = []
    catalog = await _tools_catalog(session["integrations"])

    @tool
    def mcp_call(tool_name: str, arguments_json: str = "{}") -> str:
        """Call MCP tool by name. arguments_json is JSON object string."""
        import asyncio
        return asyncio.run(_mcp_call(tool_name, arguments_json, tool_log))

    llm = LLM(
        model=MODEL,
        base_url=OPENROUTER_BASE,
        api_key=os.getenv("OPENROUTER_API_KEY"),
    )

    assistant = Agent(
        role="Personal Assistant",
        goal="Help the user using MCP integrations",
        backstory=(
            f"You are {ASSISTANT_NAME}. Use mcp_call for tools.\n"
            f"Available tools:\n{catalog}"
        ),
        llm=llm,
        tools=[mcp_call],
        verbose=False,
    )

    task = Task(
        description=f"Reply to the user.\n\nUser: {user_message}",
        expected_output="Clear helpful answer.",
        agent=assistant,
    )

    result = Crew(agents=[assistant], tasks=[task], verbose=False).kickoff()
    return {
        "ok": True,
        "reply": str(result),
        "tool_calls_used": tool_log,
        "framework": "crewai",
        "integrations": session["integrations"],
    }


async def chat(session_id: str, user_message: str) -> dict:
    session = get_session(session_id)
    if not session:
        return {"ok": False, "error": "Session not found. Start a new session."}

    init_hub()
    user_message = user_message.strip()
    if not user_message:
        return {"ok": False, "error": "Empty message."}

    try:
        if session["framework"] == "crewai":
            return await _chat_crewai(session, user_message)
        return await _chat_langgraph(session, user_message)
    except Exception as e:
        log.exception("agent chat failed")
        return {"ok": False, "error": str(e), "framework": session.get("framework")}
