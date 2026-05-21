"""Logging for MCP Studio tool calls (shows in uvicorn terminal)."""

import json
import logging
import os
from pathlib import Path

LOG_LEVEL = os.getenv("MCP_STUDIO_LOG", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [studio] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("proxystudio")

GWORKSPACE_CREDS_DIR = Path.home() / ".local/share/google-workspace-mcp/credentials"
GWORKSPACE_ACCOUNTS = Path.home() / ".config/google-workspace-mcp/accounts.json"


def _email_to_cred_filename(email: str) -> str:
    return email.replace("@", "_at_").replace(".", "_dot_") + ".json"


def check_gworkspace_email(email: str) -> dict:
    """Check on-disk Google Workspace credential before calling Gmail tools."""
    path = GWORKSPACE_CREDS_DIR / _email_to_cred_filename(email)
    info = {
        "email": email,
        "credential_path": str(path),
        "exists": path.exists(),
        "type": None,
        "ok": False,
        "hint": "",
    }

    if not path.exists():
        info["hint"] = (
            "No token file. Run tool gworkspace_manage_accounts with "
            '{"operation": "authenticate"} and sign in in the browser.'
        )
        return info

    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        info["hint"] = f"Credential file is not valid JSON: {e}"
        return info

    info["type"] = data.get("type")
    keys = list(data.keys())

    if "installed" in keys or "web" in keys:
        info["hint"] = (
            "Wrong file: OAuth client secret JSON was copied here. "
            "Delete this file, then run gworkspace_manage_accounts authenticate "
            "(do not copy client_secret_*.json into credentials/)."
        )
        return info

    if data.get("type") != "authorized_user":
        info["hint"] = (
            f'Expected type "authorized_user", got {repr(data.get("type"))}. '
            "Re-run authenticate."
        )
        return info

    if not data.get("refresh_token"):
        info["hint"] = "Missing refresh_token. Re-run authenticate."
        return info

    info["ok"] = True
    info["hint"] = "Credential file looks valid."
    return info


def log_tool_request(tool_name: str, arguments: dict, extra: dict | None = None):
    safe_args = json.dumps(arguments, default=str)
    parts = [f"tool={tool_name}", f"args={safe_args}"]
    if extra:
        for k, v in extra.items():
            parts.append(f"{k}={v}")
    log.info(" → call %s", " | ".join(parts))


def log_tool_response(tool_name: str, ok: bool, preview: str = "", error: str = ""):
    if ok:
        text = (preview or "")[:500]
        log.info(" ← ok %s | %s", tool_name, text.replace("\n", " ")[:200])
    else:
        log.error(" ← fail %s | %s", tool_name, error)


# Extra fields per operation (beyond operation + email)
GWORKSPACE_EMAIL_NEEDS = {
    "read": ["messageId"],
    "send": ["to", "subject", "body"],
    "reply": ["messageId", "body"],
    "replyAll": ["messageId", "body"],
    "forward": ["messageId", "to"],
    "trash": ["messageId"],
    "untrash": ["messageId"],
    "getAttachment": ["messageId", "filename"],
    "viewAttachment": ["messageId", "filename"],
    "modify": ["messageId"],
    "getThread": ["threadId"],
}

TOOL_EXAMPLES = {
    "gworkspace_manage_email": {
        "search": {
            "operation": "search",
            "email": "you@gmail.com",
            "query": "from:github",
            "maxResults": 5,
        },
        "read": {
            "operation": "read",
            "email": "you@gmail.com",
            "messageId": "PASTE_MESSAGE_ID_FROM_SEARCH",
            "bodyFormat": "plain",
        },
        "triage": {
            "operation": "triage",
            "email": "you@gmail.com",
        },
    },
    "gworkspace_manage_accounts": {
        "authenticate": {"operation": "authenticate"},
    },
}


def validate_gworkspace_tool(tool_name: str, args: dict) -> dict | None:
    """Catch common argument mistakes before calling the MCP server."""
    if tool_name == "gworkspace_manage_email":
        op = args.get("operation")
        if op == "read" and not args.get("messageId"):
            return {
                "ok": False,
                "tool": tool_name,
                "error": "read requires messageId (Gmail message ID), not query/maxResults alone.",
                "hint": (
                    "1) Run search with query to list emails.\n"
                    "2) Copy messageId from the search result.\n"
                    "3) Run read with that messageId."
                ),
                "example": TOOL_EXAMPLES["gworkspace_manage_email"]["search"],
                "debug": {"arguments": args, "operation": op},
            }
        needs = GWORKSPACE_EMAIL_NEEDS.get(op, [])
        missing = [f for f in needs if not args.get(f)]
        if missing:
            return {
                "ok": False,
                "tool": tool_name,
                "error": f"operation '{op}' also needs: {', '.join(missing)}",
                "hint": "See the tool schema description for this operation.",
                "debug": {"arguments": args, "missing": missing},
            }
    if tool_name == "gworkspace_manage_accounts" and args.get("operation") == "authenticate":
        log.info("gworkspace authenticate — browser OAuth should open")
    return None
