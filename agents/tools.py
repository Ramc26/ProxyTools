import json
import os

from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI

from helper import HUB_ID, init_hub, run_tool
from mcp_hub import mcp
from servers import EXTERNAL_SERVERS
from studio_log import (
    log_agent_step,
    log_agent_tool_call,
    log_agent_tool_result,
)

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MAX_TOOLS_FOR_LLM = 80
TOOL_CATALOGS = {}


def env_ready(env_keys):
    if not env_keys:
        return True
    for key in env_keys:
        if not os.getenv(key):
            return False
    return True


def is_model_error(exc):
    text = str(exc).lower()
    if isinstance(exc, ValueError):
        if "provider" in text or "502" in text or "503" in text or "429" in text:
            return True
    for code in ["502", "503", "429", "500", "overloaded", "rate limit"]:
        if code in text:
            return True
    return False


def preview_text(text, limit=280):
    txt = (text or "").replace("\n", " ").strip()
    if len(txt) <= limit:
        return txt
    return txt[: limit - 3] + "..."


def message_text(content):
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


def tool_allowed(name, integrations):
    is_external = False
    for server in EXTERNAL_SERVERS:
        if name.startswith(server["namespace"] + "_"):
            is_external = True
            break

    if not is_external:
        return HUB_ID in integrations

    for ns in integrations:
        if ns != HUB_ID and name.startswith(ns + "_"):
            return True
    return False


async def picked_mcp_tools(integrations):
    all_tools = await mcp.list_tools()
    picked = []
    for tool in all_tools:
        if tool_allowed(tool.name, integrations):
            picked.append(tool)
    return picked[:MAX_TOOLS_FOR_LLM]


async def tools_catalog(integrations):
    key = ",".join(sorted(integrations))
    if key in TOOL_CATALOGS:
        return TOOL_CATALOGS[key]

    lines = []
    tools = await picked_mcp_tools(integrations)
    for tool in tools:
        desc = (tool.description or "")[:120].replace("\n", " ")
        lines.append("- " + tool.name + ": " + desc)

    catalog = "\n".join(lines)
    if not catalog:
        catalog = "(no tools)"
    TOOL_CATALOGS[key] = catalog
    return catalog


def make_llm(model_name=None):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("Set OPENAI_API_KEY in .env")
    use_model = model_name or MODEL
    return ChatOpenAI(model=use_model, api_key=api_key, temperature=0.3)


async def mcp_call(tool_name, arguments_json="{}", tool_log=None, steps=None, step_no=None, session=None):
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError as err:
        return "Invalid JSON arguments: " + str(err)

    if not isinstance(args, dict):
        return "arguments_json must be a JSON object"

    if session and session.get("gworkspace_email"):
        if tool_name.startswith("gworkspace_") and not args.get("email"):
            args["email"] = session["gworkspace_email"]

    log_agent_tool_call(tool_name, args)
    if step_no is not None and steps is not None:
        step_no[0] = step_no[0] + 1
        n = step_no[0]
        steps.append({"step": n, "type": "tool_call", "tool": tool_name, "args": args})
        log_agent_step(n, "tool_call", tool_name, {"args": args})

    result = await run_tool(tool_name, args)
    ok = bool(result.get("ok"))
    body = result.get("result") or ""
    err = result.get("error", "tool failed")
    if result.get("hint"):
        err = err + "\nHint: " + result["hint"]

    log_agent_tool_result(tool_name, ok, body if ok else "", err if not ok else "")

    if step_no is not None and steps is not None:
        step_no[0] = step_no[0] + 1
        n = step_no[0]
        steps.append(
            {
                "step": n,
                "type": "tool_result",
                "tool": tool_name,
                "ok": ok,
                "preview": preview_text(body if ok else err),
            }
        )
        log_agent_step(
            n,
            "tool_result",
            "%s %s" % (tool_name, "ok" if ok else "failed"),
            {"preview": preview_text(body if ok else err)},
        )

    entry = {"tool": tool_name, "ok": ok, "args": args, "preview": preview_text(body if ok else err)}
    if tool_log is not None:
        tool_log.append(entry)

    if ok:
        return body or "(empty)"
    return err


async def make_langchain_mcp_tool(tool_log, steps, step_no, session):
    async def _run(tool_name, arguments_json="{}"):
        return await mcp_call(tool_name, arguments_json, tool_log, steps, step_no, session)

    return StructuredTool.from_function(
        coroutine=_run,
        name="mcp_call",
        description=(
            "Call an MCP tool by exact name. arguments_json is a JSON object string "
            'matching the tool schema (example: {"operation":"search","email":"you@x.com"}).'
        ),
    )


def list_framework_rows():
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


def list_integration_rows():
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
    for server in EXTERNAL_SERVERS:
        env_keys = server.get("env_keys", [])
        rows.append(
            {
                "id": server["namespace"],
                "title": server.get("title") or server["namespace"],
                "description": server.get("package") or server.get("url", ""),
                "env_ready": env_ready(env_keys),
                "env_keys": env_keys,
                "default_on": False,
            }
        )
    return rows


def _gitlab_rules():
    lines = []
    lines.append("GitLab guidance:")
    lines.append("- For 'projects I am member of', use gitlab_list_projects with {'membership': true, 'per_page': 100}.")
    lines.append("- For 'projects in group X', use gitlab_list_group_projects with {'group_id': '<full_group_path_or_id>', 'include_subgroups': true}.")
    lines.append("- Use gitlab_list_namespaces only to discover users/groups.")
    lines.append("- Do not use gitlab_search_repositories for group-membership listing.")
    lines.append("- For project tools, use numeric project_id or full URL-encoded path.")
    return "\n".join(lines)


def _gworkspace_rules(email):
    if not email:
        return ""
    return (
        "Google Workspace guidance:\n"
        f"- For gworkspace_* tools, use email '{email}' when required.\n"
        "- If an operation requires messageId/threadId, search first and then call read/getThread."
    )


def _postman_rules():
    return (
        "Postman guidance:\n"
        "- Use Postman tools for collections, requests, and API execution.\n"
        "- Keep request inputs explicit (workspace, collection, environment) when available."
    )


def _github_rules():
    return (
        "GitHub guidance:\n"
        "- Use GitHub tools for repo/PR/issues operations.\n"
        "- Confirm repo owner/name before branch or PR actions."
    )


def _integration_backstory(integrations):
    parts = []
    if "gitlab" in integrations:
        parts.append(_gitlab_rules())
    if "gworkspace" in integrations:
        parts.append("Google Workspace is enabled for email/calendar operations.")
    if "postman" in integrations:
        parts.append(_postman_rules())
    if "github" in integrations:
        parts.append(_github_rules())
    if "brave" in integrations:
        parts.append("Brave Search is enabled for web lookup and summarization.")
    if "hub" in integrations:
        parts.append("Hub tools are local helper tools for ping/echo and checks.")
    return "\n\n".join(parts)


def build_langgraph_system_prompt(assistant_name, integrations, catalog, gworkspace_email):
    chunks = []
    chunks.append(f"You are {assistant_name}, a helpful personal assistant.")
    chunks.append(f"Integrations enabled: {', '.join(integrations)}.")
    chunks.append("Use mcp_call(tool_name, arguments_json) to run tools.")
    chunks.append(_integration_backstory(integrations))
    gws = _gworkspace_rules(gworkspace_email)
    if gws:
        chunks.append(gws)
    chunks.append("Available tools:\n" + catalog)
    return "\n\n".join(chunks)


def build_crewai_backstory(assistant_name, integrations, catalog, gworkspace_email):
    chunks = []
    chunks.append(f"You are {assistant_name}. Help users with MCP integrations.")
    chunks.append("Use mcp_call for all tool execution.")
    chunks.append(_integration_backstory(integrations))
    gws = _gworkspace_rules(gworkspace_email)
    if gws:
        chunks.append(gws)
    chunks.append("Available tools:\n" + catalog)
    return "\n\n".join(chunks)

