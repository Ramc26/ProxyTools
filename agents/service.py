import os
import uuid

from helper import HUB_ID
from helper import init_hub
from studio_log import (
    log,
    log_agent_fallback,
    log_agent_turn_end,
    log_agent_turn_start,
)

from .crew import run_crew_once
from .langgraph import run_langgraph_once
from .tools import is_model_error, list_framework_rows, list_integration_rows

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
BACKUP_MODEL = os.getenv("OPENAI_BACKUP_MODEL", "").strip()
if not BACKUP_MODEL:
    BACKUP_MODEL = None

ASSISTANT_NAME = "RamBabu"
ASSISTANT_INITIALS = "RB"

SESSIONS = {}


def list_frameworks():
    return list_framework_rows()


def list_integrations():
    return list_integration_rows()


def create_session(integrations, framework="langgraph", gworkspace_email=None):
    if not integrations:
        integrations = [HUB_ID]
    if framework not in ["langgraph", "crewai"]:
        framework = "langgraph"

    gws_email = None
    if gworkspace_email:
        gws_email = gworkspace_email.strip()
        if not gws_email:
            gws_email = None

    if "gworkspace" in integrations and not gws_email:
        return {
            "ok": False,
            "error_code": "gworkspace_email_required",
            "error": "Select a Google Workspace account before starting the session.",
        }

    session_id = str(uuid.uuid4())[:8]
    SESSIONS[session_id] = {
        "id": session_id,
        "integrations": integrations,
        "framework": framework,
        "gworkspace_email": gws_email,
        "started": False,
    }
    row = {
        "ok": True,
        "session_id": session_id,
        "integrations": integrations,
        "framework": framework,
        "gworkspace_email": gws_email,
    }
    if row.get("ok"):
        row["assistant"] = ASSISTANT_NAME
        row["primary_model"] = MODEL
        row["backup_model"] = BACKUP_MODEL
    return row


def get_session(session_id):
    return SESSIONS.get(session_id)


async def _chat_langgraph(session, user_message):
    tool_log = []
    steps = []
    models_to_try = [MODEL]
    if BACKUP_MODEL and BACKUP_MODEL != MODEL:
        models_to_try.append(BACKUP_MODEL)

    log_agent_turn_start(session["id"], session["framework"], user_message, models_to_try[0])

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
            reply, steps = await run_langgraph_once(
                session, user_message, model, tool_log, steps, ASSISTANT_NAME
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
        except Exception as err:
            last_error = err
            if is_model_error(err) and idx < len(models_to_try) - 1:
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


async def _chat_crewai(session, user_message):
    tool_log = []
    steps = []
    models_to_try = [MODEL]
    if BACKUP_MODEL and BACKUP_MODEL != MODEL:
        models_to_try.append(BACKUP_MODEL)

    log_agent_turn_start(session["id"], "crewai", user_message, models_to_try[0])

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
            reply, steps = await run_crew_once(
                session, user_message, model, tool_log, steps, ASSISTANT_NAME
            )
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
        except Exception as err:
            last_error = err
            if is_model_error(err) and idx < len(models_to_try) - 1:
                continue
            log.exception("agent chat failed (crewai)")
            log_agent_turn_end(session["id"], False, model, len(steps))
            raise

    return {"ok": False, "error": str(last_error), "framework": "crewai"}


async def chat(session_id, user_message):
    session = get_session(session_id)
    if not session:
        return {"ok": False, "error": "Session not found. Start a new session."}

    init_hub()
    msg = (user_message or "").strip()
    if not msg:
        return {"ok": False, "error": "Empty message."}

    try:
        if session.get("framework") == "crewai":
            return await _chat_crewai(session, msg)
        return await _chat_langgraph(session, msg)
    except Exception as err:
        if BACKUP_MODEL:
            hint = (
                "OpenAI error — set OPENAI_API_KEY in .env. "
                "Backup model %s is tried on rate limits when configured." % BACKUP_MODEL
            )
        else:
            hint = "OpenAI error — set OPENAI_API_KEY in .env. Primary model: %s." % MODEL
        return {
            "ok": False,
            "error": str(err),
            "framework": session.get("framework"),
            "hint": hint,
        }

