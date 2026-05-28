"""Logging for MCP Studio — tools and agent turns (human-readable terminal output)."""

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

_LINE = "─" * 52
_BOX = "═" * 52
_MCP_BOX = "┄" * 52


def _trunc(text, n=200):
    t = (text or "").replace("\n", " ").strip()
    return t if len(t) <= n else t[: n - 3] + "..."


def _json_text(data, n=600):
    try:
        return _trunc(json.dumps(data, default=str, separators=(",", ":")), n)
    except Exception:
        return _trunc(str(data), n)


def log_agent_turn_start(session_id, framework, user_message, model):
    log.info("")
    log.info(_BOX)
    log.info("  AGENT TURN")
    log.info("  session:   %s", session_id)
    log.info("  framework: %s", framework)
    log.info("  model:     %s", model)
    log.info(_LINE)
    log.info("  User: %s", _trunc(user_message, 300))


def log_agent_turn_end(session_id, ok, model_used, step_count, reply_preview=""):
    status = "OK" if ok else "FAILED"
    log.info(_LINE)
    log.info("  Turn %s · model=%s · steps=%d", status, model_used, step_count)
    if reply_preview:
        log.info("  Reply: %s", _trunc(reply_preview, 400))
    log.info(_BOX)
    log.info("")


def log_agent_step(step, kind, detail="", extra=None):
    """Human-readable step line for agent reasoning loop."""
    label = kind.upper().ljust(12)
    line = f"  Step {step:>2} · {label}"
    if detail:
        line += f" · {detail}"
    log.info(line)
    if extra:
        for k, v in extra.items():
            if v is None or v == "":
                continue
            if isinstance(v, dict):
                v = json.dumps(v, default=str)
            log.info("           %-10s %s", f"{k}:", _trunc(str(v), 350))


def log_agent_llm(model, note="request"):
    log.info("  · LLM %s · model=%s", note, model)


def log_agent_tool_call(tool_name, args):
    log.info("  %s", _MCP_BOX)
    log.info("  ┌─ TOOL CALL   %s", tool_name)
    log.info("  │  INPUT       %s", _json_text(args))
    log.info("  └────────────────────────────────────────────")


def log_agent_tool_result(tool_name, ok, preview="", error=""):
    status = "OK" if ok else "FAIL"
    log.info("  ┌─ TOOL RESULT %s   %s", status, tool_name)
    if ok and preview:
        log.info("  │  OUTPUT      %s", _trunc(preview, 500))
    elif error:
        log.info("  │  ERROR       %s", _trunc(error, 500))
    log.info("  └────────────────────────────────────────────")


def log_agent_fallback(failed_model, backup_model, error):
    log.warning(_LINE)
    log.warning("  ⚠ PRIMARY MODEL FAILED")
    log.warning("           failed:  %s", failed_model)
    log.warning("           reason:  %s", _trunc(error, 300))
    log.warning("           retry:   %s", backup_model)
    log.warning(_LINE)


def log_tool_request(tool_name, arguments, extra=None):
    parts = []
    if extra:
        for k, v in extra.items():
            parts.append(f"{k}={v}")
    suffix = f" | {' | '.join(parts)}" if parts else ""
    log.info("  %s", _MCP_BOX)
    log.info("  ┌─ MCP REQUEST %s%s", tool_name, suffix)
    log.info("  │  INPUT       %s", _json_text(arguments))
    log.info("  └────────────────────────────────────────────")


def log_tool_response(tool_name, ok, preview="", error=""):
    status = "OK" if ok else "FAIL"
    log.info("  ┌─ MCP RESPONSE %s   %s", status, tool_name)
    if ok:
        text = (preview or "").replace("\n", " ")
        log.info("  │  OUTPUT      %s", _trunc(text, 260))
    else:
        log.error("  │  ERROR       %s", _trunc(error or preview, 260))
    log.info("  └────────────────────────────────────────────")


def check_gworkspace_email(email):
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


def _email_to_cred_filename(email):
    return email.replace("@", "_at_").replace(".", "_dot_") + ".json"


def _cred_filename_to_email(stem):
    return stem.replace("_at_", "@").replace("_dot_", ".")


def gworkspace_test_users_allowlist():
    """Comma-separated GWORKSPACE_TEST_USERS in .env; None = no allowlist enforcement."""
    raw = os.getenv("GWORKSPACE_TEST_USERS", "").strip()
    if not raw:
        return None
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def gworkspace_enforce_test_users():
    return gworkspace_test_users_allowlist() is not None


def is_gworkspace_email_allowed(email):
    allowlist = gworkspace_test_users_allowlist()
    if allowlist is None:
        return True, None
    normalized = email.strip().lower()
    if normalized in allowlist:
        return True, None
    return (
        False,
        f"{email} is not on the app's OAuth test users list. "
        "Ask your developer or admin to add this email in Google Cloud Console "
        "(APIs & Services → OAuth consent screen → Audience → Test users) "
        "before authenticating.",
    )


def classify_gworkspace_auth_error(error_text):
    """Map Google OAuth errors to a clearer test-user message when applicable."""
    lower = (error_text or "").lower()
    markers = (
        "access_denied",
        "test user",
        "not authorized",
        "not a test user",
        "has not been granted",
        "403",
        "invalid_grant",
    )
    if not any(m in lower for m in markers):
        return None
    return {
        "error_code": "google_oauth_denied",
        "error": (
            "Google rejected sign-in for this email. While the app is in Testing mode, "
            "the address must be added under OAuth consent screen → Test users."
        ),
        "hint": (
            "Ask your developer or admin to add this email to the test users list, "
            "then try Authenticate again."
        ),
    }


def list_gworkspace_accounts():
    """Accounts from accounts.json plus credential files on disk."""
    rows = []
    seen = set()

    def add_row(email, category=None):
        key = email.strip().lower()
        if not key or key in seen:
            return
        seen.add(key)
        cred = check_gworkspace_email(email)
        allowed, block_reason = is_gworkspace_email_allowed(email)
        rows.append(
            {
                "email": email,
                "category": category,
                "authenticated": cred["ok"],
                "credential_exists": cred["exists"],
                "allowed_to_authenticate": allowed,
                "block_reason": block_reason,
            }
        )

    if GWORKSPACE_ACCOUNTS.exists():
        try:
            data = json.loads(GWORKSPACE_ACCOUNTS.read_text())
            for acc in data.get("accounts") or []:
                if isinstance(acc, dict) and acc.get("email"):
                    add_row(acc["email"], acc.get("category"))
        except (json.JSONDecodeError, OSError):
            pass

    if GWORKSPACE_CREDS_DIR.is_dir():
        for path in GWORKSPACE_CREDS_DIR.glob("*.json"):
            add_row(_cred_filename_to_email(path.stem))

    rows.sort(key=lambda r: r["email"].lower())
    allowlist = gworkspace_test_users_allowlist()
    return {
        "accounts": rows,
        "enforce_test_users": gworkspace_enforce_test_users(),
        "test_users_count": len(allowlist) if allowlist else 0,
        "credentials_dir": str(GWORKSPACE_CREDS_DIR),
    }


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
        "authenticate": {
            "operation": "authenticate",
            "email": "you@company.com",
        },
    },
}


def validate_gworkspace_tool(tool_name, args):
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
