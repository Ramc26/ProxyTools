import json
import os
import time
import traceback
from pathlib import Path
from typing import Any

from mcp_hub import MOUNT_STATUS, mcp, mount_external_servers
from servers import EXTERNAL_SERVERS
from studio_log import (
    TOOL_EXAMPLES,
    check_gworkspace_email,
    log,
    log_tool_request,
    log_tool_response,
    validate_gworkspace_tool,
)

_hub_ready = False

HUB_ID = "hub"
HUB_META = {"title": "Hub (local)", "subtitle": "Tools on this integration server"}

PROJECT_ROOT = Path(__file__).parent
INSPECTOR_CMD = "npx -y @modelcontextprotocol/inspector uv run python mcp_hub.py"


def _namespaces():
    return [HUB_ID] + [s["namespace"] for s in EXTERNAL_SERVERS]


def _title(server_cfg):
    return server_cfg.get("title") or server_cfg["namespace"].replace("_", " ").title()


def _subtitle(server_cfg):
    return server_cfg.get("package") or server_cfg.get("url", "")


def _tool_server(tool_name):
    for s in EXTERNAL_SERVERS:
        if tool_name.startswith(s["namespace"] + "_"):
            return s["namespace"]
    return HUB_ID


def _tool_dict(tool):
    data = tool.model_dump()
    schema = data.get("parameters") or {}
    props = schema.get("properties") or {}
    return {
        "name": data.get("name") or tool.name,
        "title": data.get("title"),
        "description": data.get("description") or "",
        "required": list(schema.get("required") or []),
        "has_required": bool(schema.get("required")),
        "property_names": list(props.keys()),
        "schema_json": json.dumps(schema, indent=2),
        "examples": TOOL_EXAMPLES.get(data.get("name") or tool.name, {}),
    }


def _env_status(env_keys):
    missing = [k for k in env_keys if not os.getenv(k)]
    return {
        "ready": len(missing) == 0,
        "missing": missing,
    }


def init_hub():
    global _hub_ready
    if not _hub_ready:
        mount_external_servers()
        _hub_ready = True


def _result_to_text(result) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    content = getattr(result, "content", None)
    if not content:
        return str(result)
    parts = []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts) if parts else str(result)


def filter_options():
    opts = [{"id": None, "label": "All"}]
    opts.append({"id": HUB_ID, "label": HUB_META["title"]})
    for s in EXTERNAL_SERVERS:
        opts.append({"id": s["namespace"], "label": _title(s)})
    return opts


def get_configured_servers():
    """All entries from servers.py with env check (before mount)."""
    rows = [
        {
            "namespace": HUB_ID,
            "title": HUB_META["title"],
            "connection": "local",
            "source": "mcp_hub.py",
            "env_keys": [],
            "env": {"ready": True, "missing": []},
        }
    ]
    for s in EXTERNAL_SERVERS:
        env_keys = s.get("env_keys", [])
        rows.append(
            {
                "namespace": s["namespace"],
                "title": _title(s),
                "connection": s.get("connection", "stdio"),
                "source": _subtitle(s),
                "env_keys": env_keys,
                "env": _env_status(env_keys),
            }
        )
    return rows


def get_mount_status_with_counts(tool_counts: dict):
    status = []
    for row in MOUNT_STATUS:
        ns = row["namespace"]
        copy = dict(row)
        copy["tool_count"] = tool_counts.get(ns, 0)
        status.append(copy)
    return status


def _gworkspace_preflight(tool_name: str, args: dict) -> dict | None:
    """Return error payload if Google Workspace creds are wrong, else None."""
    if not tool_name.startswith("gworkspace_"):
        return None
    email = args.get("email")
    if not email:
        return None
    cred = check_gworkspace_email(email)
    log.info(
        "gworkspace cred check | email=%s | path=%s | exists=%s | type=%s",
        email,
        cred["credential_path"],
        cred["exists"],
        cred["type"],
    )
    if cred["ok"]:
        return None
    return {
        "ok": False,
        "tool": tool_name,
        "error": f"Invalid credential for {email}: expected type \"authorized_user\", got {repr(cred['type'])}",
        "hint": cred["hint"],
        "debug": {"credential": cred, "arguments": args},
    }


async def run_tool(tool_name: str, arguments: dict | None = None) -> dict[str, Any]:
    init_hub()
    args = arguments or {}
    server = _tool_server(tool_name)

    log_tool_request(
        tool_name,
        args,
        extra={"upstream": server, "operation": args.get("operation")},
    )

    preflight = _gworkspace_preflight(tool_name, args)
    if preflight:
        log_tool_response(tool_name, False, error=preflight["error"])
        return preflight

    arg_check = validate_gworkspace_tool(tool_name, args)
    if arg_check:
        log_tool_response(tool_name, False, error=arg_check["error"])
        return arg_check

    t0 = time.perf_counter()
    try:
        result = await mcp.call_tool(tool_name, args)
        text = _result_to_text(result)
        log_tool_response(tool_name, True, preview=text)
        return {
            "ok": True,
            "tool": tool_name,
            "result": text,
            "debug": {
                "upstream": server,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000),
            },
        }
    except Exception as e:
        log.error("traceback:\n%s", traceback.format_exc())
        log_tool_response(tool_name, False, error=str(e))
        return {
            "ok": False,
            "tool": tool_name,
            "error": str(e),
            "debug": {
                "upstream": server,
                "arguments": args,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000),
            },
        }


async def test_hub_ping() -> dict[str, Any]:
    return await run_tool("hub_ping", {})


async def get_studio_data(server_filter=None):
    init_hub()
    tools = await mcp.list_tools()

    grouped = {ns: [] for ns in _namespaces()}
    tool_counts = {ns: 0 for ns in _namespaces()}

    for tool in tools:
        item = _tool_dict(tool)
        sid = _tool_server(item["name"])
        grouped.setdefault(sid, []).append(item)
        tool_counts[sid] = tool_counts.get(sid, 0) + 1

    for items in grouped.values():
        items.sort(key=lambda t: t["name"])

    servers_out = []

    def add_block(sid, title, subtitle):
        if server_filter and sid != server_filter:
            return
        tools_list = grouped.get(sid, [])
        servers_out.append(
            {
                "id": sid,
                "title": title,
                "subtitle": subtitle,
                "tool_count": len(tools_list),
                "tools": tools_list,
            }
        )

    add_block(HUB_ID, HUB_META["title"], HUB_META["subtitle"])
    for s in EXTERNAL_SERVERS:
        add_block(s["namespace"], _title(s), _subtitle(s))

    return {
        "total_tools": sum(x["tool_count"] for x in servers_out),
        "servers": servers_out,
        "filter_options": filter_options(),
        "configured_servers": get_configured_servers(),
        "mount_status": get_mount_status_with_counts(tool_counts),
        "inspector_cmd": INSPECTOR_CMD,
        "tool_counts": tool_counts,
    }


async def get_tools_grouped(server_filter=None):
    data = await get_studio_data(server_filter)
    return {
        "total_tools": data["total_tools"],
        "servers": data["servers"],
        "filter_options": data["filter_options"],
    }
