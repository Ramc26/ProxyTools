import json
from typing import Any

from conflict import EXTERNAL_SERVERS, mcp, mount_external_servers

_hub_ready = False

# Display info for each server group in the UI
SERVER_LABELS = {
    "hub": {
        "title": "Hub (local)",
        "subtitle": "Tools defined on this integration server",
    },
    "github": {
        "title": "GitHub",
        "subtitle": "@modelcontextprotocol/server-github",
    },
    "postman": {
        "title": "Postman",
        "subtitle": "https://mcp.postman.com/mcp",
    },
}


def _server_for_tool_name(name: str) -> str:
    if name.startswith("github_"):
        return "github"
    if name.startswith("postman_"):
        return "postman"
    return "hub"


def _required_fields(schema: dict | None) -> list[str]:
    if not schema or not isinstance(schema, dict):
        return []
    return list(schema.get("required") or [])


def tool_to_dict(tool) -> dict[str, Any]:
    data = tool.model_dump()
    schema = data.get("parameters") or {}
    return {
        "name": data.get("name") or tool.name,
        "title": data.get("title"),
        "description": data.get("description") or "",
        "input_schema": schema,
        "required": _required_fields(schema),
        "annotations": data.get("annotations"),
        "schema_json": json.dumps(schema, indent=2),
    }


def init_hub():
    global _hub_ready
    if _hub_ready:
        return
    mount_external_servers()
    _hub_ready = True


async def get_tools_grouped(server_filter: str | None = None) -> dict[str, Any]:
    init_hub()
    tools = await mcp.list_tools()

    grouped: dict[str, list] = {"hub": [], "github": [], "postman": []}
    for tool in tools:
        item = tool_to_dict(tool)
        server = _server_for_tool_name(item["name"])
        if server not in grouped:
            grouped[server] = []
        grouped[server].append(item)

    for key in grouped:
        grouped[key].sort(key=lambda t: t["name"])

    if server_filter:
        if server_filter not in grouped:
            grouped = {server_filter: []}
        else:
            grouped = {server_filter: grouped[server_filter]}

    servers_out = []
    order = ["hub", "github", "postman"]
    for key in order:
        if key not in grouped:
            continue
        if server_filter and key != server_filter:
            continue
        tools_list = grouped.get(key, [])
        meta = SERVER_LABELS.get(key, {"title": key, "subtitle": ""})
        servers_out.append(
            {
                "id": key,
                "title": meta["title"],
                "subtitle": meta["subtitle"],
                "tool_count": len(tools_list),
                "tools": tools_list,
            }
        )

    return {
        "total_tools": sum(s["tool_count"] for s in servers_out),
        "servers": servers_out,
        "configured_externals": [s["namespace"] for s in EXTERNAL_SERVERS],
    }
