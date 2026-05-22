"""
RamBabu agent — LangGraph (default) or CrewAI, with MCP tools from selected integrations.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from helper import HUB_ID, init_hub, run_tool
from mcp_hub import mcp
from servers import EXTERNAL_SERVERS
from studio_log import (
    log,
    log_agent_fallback,
    log_agent_llm,
    log_agent_step,
    log_agent_tool_call,
    log_agent_tool_result,
    log_agent_turn_end,
    log_agent_turn_start,
)

load_dotenv()

MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/owl-alpha")
BACKUP_MODEL = os.getenv(
    "OPENROUTER_BACKUP_MODEL", "nvidia/nemotron-3-super-120b-a12b:free"
)
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
ASSISTANT_NAME = "RamBabu"
ASSISTANT_INITIALS = "RB"
MAX_TOOLS_FOR_LLM = 80

_sessions: dict[str, dict[str, Any]] = {}
_memory = MemorySaver()
_tool_catalogs: dict[str, str] = {}


def _env_ready(env_keys: list) -> bool:
    return all(os.getenv(k) for k in env_keys) if env_keys else True


def _is_model_error(exc: Exception) -> bool:
    text = str(exc).lower()
    if isinstance(exc, ValueError):
        if "provider" in text or "502" in text or "503" in text or "429" in text:
            return True
    for code in ("502", "503", "429", "500", "overloaded", "rate limit"):
        if code in text:
            return True
    return False


def _message_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


def _preview(text: str, n: int = 280) -> str:
    t = (text or "").replace("\n", " ").strip()
    return t if len(t) <= n else t[: n - 3] + "..."


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


def _llm(model: str | None = None):
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("Set OPENROUTER_API_KEY in .env")
    use_model = model or MODEL
    return ChatOpenAI(
        model=use_model,
        api_key=api_key,
        base_url=OPENROUTER_BASE,
        temperature=0.3,
    )


async def _mcp_call(
    tool_name: str,
    arguments_json: str = "{}",
    tool_log: list | None = None,
    steps: list | None = None,
    step_no: list | None = None,
) -> str:
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError as e:
        return f"Invalid JSON arguments: {e}"
    if not isinstance(args, dict):
        return "arguments_json must be a JSON object"

    log_agent_tool_call(tool_name, args)
    if step_no is not None and steps is not None:
        n = step_no[0] = step_no[0] + 1
        steps.append(
            {
                "step": n,
                "type": "tool_call",
                "tool": tool_name,
                "args": args,
            }
        )
        log_agent_step(n, "tool_call", tool_name, {"args": args})

    result = await run_tool(tool_name, args)
    ok = bool(result.get("ok"))
    body = result.get("result") or ""
    err = result.get("error", "tool failed")
    if result.get("hint"):
        err += "\nHint: " + result["hint"]

    log_agent_tool_result(tool_name, ok, body if ok else "", err if not ok else "")
    if step_no is not None and steps is not None:
        n = step_no[0] = step_no[0] + 1
        steps.append(
            {
                "step": n,
                "type": "tool_result",
                "tool": tool_name,
                "ok": ok,
                "preview": _preview(body if ok else err),
            }
        )
        log_agent_step(
            n,
            "tool_result",
            f"{tool_name} {'ok' if ok else 'failed'}",
            {"preview": _preview(body if ok else err)},
        )

    entry = {
        "tool": tool_name,
        "ok": ok,
        "args": args,
        "preview": _preview(body if ok else err),
    }
    if tool_log is not None:
        tool_log.append(entry)

    if ok:
        return body or "(empty)"
    return err


async def _langchain_mcp_tool(
    tool_log: list, steps: list, step_no: list
) -> StructuredTool:
    async def _run(tool_name: str, arguments_json: str = "{}") -> str:
        return await _mcp_call(
            tool_name, arguments_json, tool_log, steps, step_no
        )

    return StructuredTool.from_function(
        coroutine=_run,
        name="mcp_call",
        description=(
            "Call an MCP tool by exact name. arguments_json is a JSON object string "
            'matching the tool schema (e.g. {"operation":"search","email":"..."}).'
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
        "primary_model": MODEL,
        "backup_model": BACKUP_MODEL,
    }


def get_session(session_id: str) -> dict | None:
    return _sessions.get(session_id)


def _steps_from_messages(new_messages: list, model: str, step_no: list, steps: list):
    """Record LLM/tool messages from a graph update."""
    for m in new_messages:
        if isinstance(m, AIMessage):
            if getattr(m, "tool_calls", None):
                for tc in m.tool_calls:
                    n = step_no[0] = step_no[0] + 1
                    name = tc.get("name", "unknown")
                    args = tc.get("args", {})
                    steps.append(
                        {
                            "step": n,
                            "type": "thinking",
                            "detail": f"Calling {name}",
                            "model": model,
                        }
                    )
                    log_agent_step(n, "thinking", f"plan → {name}", {"model": model})
            elif m.content:
                text = _message_text(m.content)
                if text.strip():
                    n = step_no[0] = step_no[0] + 1
                    steps.append(
                        {
                            "step": n,
                            "type": "reply",
                            "model": model,
                            "preview": _preview(text, 120),
                        }
                    )
                    log_agent_step(n, "reply", _preview(text, 80), {"model": model})
        elif isinstance(m, ToolMessage):
            n = step_no[0] = step_no[0] + 1
            steps.append(
                {
                    "step": n,
                    "type": "tool_message",
                    "tool": m.name or "mcp_call",
                    "preview": _preview(_message_text(m.content)),
                }
            )


async def _run_langgraph_graph(
    session: dict,
    user_message: str,
    model: str,
    tool_log: list,
    steps: list,
) -> tuple[str, list]:
    step_no = [0]
    catalog = await _tools_catalog(session["integrations"])
    mcp_tool = await _langchain_mcp_tool(tool_log, steps, step_no)
    graph = create_react_agent(_llm(model), [mcp_tool], checkpointer=_memory)
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

    n = step_no[0] = step_no[0] + 1
    steps.append({"step": n, "type": "llm_start", "model": model})
    log_agent_step(n, "llm_start", "processing user message", {"model": model})
    log_agent_llm(model, "invoke")

    reply = ""
    async for update in graph.astream(
        {"messages": messages}, config, stream_mode="updates"
    ):
        for node, data in update.items():
            new_msgs = data.get("messages") or []
            log.info("  · graph node: %s (%d message(s))", node, len(new_msgs))
            _steps_from_messages(new_msgs, model, step_no, steps)
            for m in new_msgs:
                if isinstance(m, AIMessage) and m.content and not getattr(
                    m, "tool_calls", None
                ):
                    reply = _message_text(m.content)

    if not reply:
        state = await graph.aget_state(config)
        for m in reversed(state.values.get("messages", [])):
            if isinstance(m, AIMessage) and m.content:
                reply = _message_text(m.content)
                break

    return reply, steps


async def _chat_langgraph(session: dict, user_message: str) -> dict:
    tool_log: list = []
    steps: list = []
    models_to_try = [MODEL]
    if BACKUP_MODEL and BACKUP_MODEL != MODEL:
        models_to_try.append(BACKUP_MODEL)

    log_agent_turn_start(
        session["id"], session["framework"], user_message, models_to_try[0]
    )

    last_error = None
    model_used = models_to_try[0]
    reply = ""

    for idx, model in enumerate(models_to_try):
        model_used = model
        steps = []
        tool_log = []
        if idx > 0:
            log_agent_fallback(models_to_try[0], model, str(last_error))
            steps.append(
                {
                    "step": 1,
                    "type": "model_fallback",
                    "from": models_to_try[0],
                    "to": model,
                    "error": str(last_error),
                }
            )
        try:
            reply, steps = await _run_langgraph_graph(
                session, user_message, model, tool_log, steps
            )
            log_agent_turn_end(session["id"], True, model_used, len(steps), reply)
            return {
                "ok": True,
                "reply": reply,
                "tool_calls_used": tool_log,
                "steps": steps,
                "framework": "langgraph",
                "integrations": session["integrations"],
                "model_used": model_used,
                "used_backup": idx > 0,
            }
        except Exception as e:
            last_error = e
            if _is_model_error(e) and idx < len(models_to_try) - 1:
                continue
            log.exception("agent chat failed")
            log_agent_turn_end(session["id"], False, model_used, len(steps))
            raise

    log_agent_turn_end(session["id"], False, model_used, len(steps))
    return {
        "ok": False,
        "error": str(last_error),
        "steps": steps,
        "framework": "langgraph",
        "model_used": model_used,
    }


async def _chat_crewai(session: dict, user_message: str) -> dict:
    from crewai import Agent, Crew, LLM, Task
    from crewai.tools import tool

    tool_log: list = []
    steps: list = []
    catalog = await _tools_catalog(session["integrations"])
    models_to_try = [MODEL]
    if BACKUP_MODEL and BACKUP_MODEL != MODEL:
        models_to_try.append(BACKUP_MODEL)

    log_agent_turn_start(
        session["id"], "crewai", user_message, models_to_try[0]
    )

    last_error = None
    for idx, model in enumerate(models_to_try):
        steps = []
        tool_log = []
        if idx > 0:
            log_agent_fallback(models_to_try[0], model, str(last_error))
            steps.append(
                {
                    "step": 1,
                    "type": "model_fallback",
                    "from": models_to_try[0],
                    "to": model,
                    "error": str(last_error),
                }
            )
        try:
            step_counter = [0]

            @tool
            def mcp_call(tool_name: str, arguments_json: str = "{}") -> str:
                """Call MCP tool by name. arguments_json is JSON object string."""
                import asyncio

                return asyncio.run(
                    _mcp_call(
                        tool_name, arguments_json, tool_log, steps, step_counter
                    )
                )

            llm = LLM(
                model=model,
                base_url=OPENROUTER_BASE,
                api_key=os.getenv("OPENROUTER_API_KEY"),
            )
            log_agent_step(1, "llm_start", "crew kickoff", {"model": model})
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
            reply = str(result)
            log_agent_turn_end(session["id"], True, model, len(steps), reply)
            return {
                "ok": True,
                "reply": reply,
                "tool_calls_used": tool_log,
                "steps": steps,
                "framework": "crewai",
                "integrations": session["integrations"],
                "model_used": model,
                "used_backup": idx > 0,
            }
        except Exception as e:
            last_error = e
            if _is_model_error(e) and idx < len(models_to_try) - 1:
                continue
            log.exception("agent chat failed (crewai)")
            log_agent_turn_end(session["id"], False, model, len(steps))
            raise

    return {"ok": False, "error": str(last_error), "framework": "crewai"}


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
        return {
            "ok": False,
            "error": str(e),
            "framework": session.get("framework"),
            "hint": (
                "Provider error — a backup model is tried automatically when configured. "
                f"Primary: {MODEL}, backup: {BACKUP_MODEL}"
            ),
        }
