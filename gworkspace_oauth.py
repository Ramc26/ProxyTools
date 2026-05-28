"""Browser-based Google OAuth for the studio UI (same browser as the web app)."""

import json
import os
import secrets
import time
from urllib.parse import urlencode

import httpx

from studio_log import (
    GWORKSPACE_ACCOUNTS,
    GWORKSPACE_CREDS_DIR,
    _email_to_cred_filename,
    classify_gworkspace_auth_error,
    is_gworkspace_email_allowed,
)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

SERVICE_SCOPE_MAP = {
    "gmail": ["https://www.googleapis.com/auth/gmail.modify"],
    "drive": ["https://www.googleapis.com/auth/drive"],
    "calendar": ["https://www.googleapis.com/auth/calendar"],
    "sheets": ["https://www.googleapis.com/auth/spreadsheets"],
    "docs": ["https://www.googleapis.com/auth/documents"],
    "tasks": ["https://www.googleapis.com/auth/tasks"],
    "slides": ["https://www.googleapis.com/auth/presentations"],
    "meet": [
        "https://www.googleapis.com/auth/meetings.space.created",
        "https://www.googleapis.com/auth/meetings.space.readonly",
        "https://www.googleapis.com/auth/meetings.space.settings",
    ],
}
BASE_SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email"]

_pending = {}
_PENDING_TTL_SEC = 600


def _scopes_for_all_services():
    scopes = set(BASE_SCOPES)
    for urls in SERVICE_SCOPE_MAP.values():
        scopes.update(urls)
    return sorted(scopes)


def redirect_uri_from_base(public_base):
    return public_base.rstrip("/") + "/api/gworkspace/oauth/callback"


def public_base_from_request(request):
    override = os.getenv("STUDIO_PUBLIC_URL", "").strip()
    if override:
        return override.rstrip("/")
    return str(request.base_url).rstrip("/")


def _purge_stale_pending():
    now = time.time()
    stale = [k for k, v in _pending.items() if now - v.get("created", 0) > _PENDING_TTL_SEC]
    for k in stale:
        _pending.pop(k, None)


def begin_oauth(email_hint, redirect_uri, category="personal"):
    allowed, block_reason = is_gworkspace_email_allowed(email_hint)
    if not allowed:
        return {
            "ok": False,
            "error_code": "not_in_test_users",
            "error": block_reason,
            "hint": (
                "Admin: add this email to GWORKSPACE_TEST_USERS in .env and to "
                "Google Cloud OAuth consent screen → Test users."
            ),
        }

    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return {
            "ok": False,
            "error_code": "missing_google_env",
            "error": "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env",
        }

    _purge_stale_pending()
    state = secrets.token_urlsafe(24)
    scopes = _scopes_for_all_services()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "login_hint": email_hint,
    }
    auth_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    _pending[state] = {
        "created": time.time(),
        "status": "pending",
        "email_hint": email_hint,
        "category": category,
        "redirect_uri": redirect_uri,
        "account_email": None,
        "error": None,
    }

    return {
        "ok": True,
        "auth_url": auth_url,
        "oauth_state": state,
        "redirect_uri": redirect_uri,
        "message": "Complete sign-in in the browser window opened from this app.",
    }


def mark_oauth_denied(state, error):
    row = _pending.get(state)
    if row:
        row["status"] = "error"
        row["error"] = error


def oauth_status(state):
    _purge_stale_pending()
    row = _pending.get(state)
    if not row:
        return {"ok": False, "status": "unknown", "error": "OAuth session expired or not found."}
    return {
        "ok": row["status"] == "success",
        "status": row["status"],
        "email": row.get("account_email"),
        "error": row.get("error"),
    }


def _save_credential(email, client_id, client_secret, refresh_token, scopes):
    GWORKSPACE_CREDS_DIR.mkdir(parents=True, exist_ok=True)
    path = GWORKSPACE_CREDS_DIR / _email_to_cred_filename(email)
    payload = {
        "type": "authorized_user",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "scopes": scopes,
    }
    path.write_text(json.dumps(payload, indent=2))
    path.chmod(0o600)


def _add_account_entry(email, category):
    GWORKSPACE_ACCOUNTS.parent.mkdir(parents=True, exist_ok=True)
    data = {"accounts": []}
    if GWORKSPACE_ACCOUNTS.exists():
        try:
            data = json.loads(GWORKSPACE_ACCOUNTS.read_text())
        except json.JSONDecodeError:
            data = {"accounts": []}
    accounts = data.setdefault("accounts", [])
    if not any(a.get("email") == email for a in accounts if isinstance(a, dict)):
        accounts.append({"email": email, "category": category})
        GWORKSPACE_ACCOUNTS.write_text(json.dumps(data, indent=2))
        GWORKSPACE_ACCOUNTS.chmod(0o600)


async def complete_oauth(code, state):
    _purge_stale_pending()
    row = _pending.get(state)
    if not row:
        return {"ok": False, "error": "Invalid or expired OAuth state."}

    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    redirect_uri = row["redirect_uri"]

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            token_resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if not token_resp.is_success:
                raise RuntimeError(f"Token exchange failed ({token_resp.status_code}): {token_resp.text}")

            token_data = token_resp.json()
            refresh = token_data.get("refresh_token")
            if not refresh:
                raise RuntimeError(
                    "No refresh_token returned. Revoke app access at "
                    "https://myaccount.google.com/permissions and try again."
                )

            access = token_data["access_token"]
            scope_str = token_data.get("scope", "")
            scopes = scope_str.split() if scope_str else _scopes_for_all_services()

            user_resp = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access}"},
            )
            if not user_resp.is_success:
                raise RuntimeError(f"Userinfo failed ({user_resp.status_code})")
            email = user_resp.json().get("email")
            if not email:
                raise RuntimeError("Could not resolve Google account email.")

        allowed, block_reason = is_gworkspace_email_allowed(email)
        if not allowed:
            row["status"] = "error"
            row["error"] = block_reason
            return {"ok": False, "error": block_reason, "error_code": "not_in_test_users"}

        _save_credential(email, client_id, client_secret, refresh, scopes)
        _add_account_entry(email, row.get("category") or "personal")

        row["status"] = "success"
        row["account_email"] = email
        return {"ok": True, "email": email}

    except Exception as e:
        row["status"] = "error"
        row["error"] = str(e)
        extra = classify_gworkspace_auth_error(str(e))
        out = {"ok": False, "error": str(e)}
        if extra:
            out.update(extra)
        return out


def callback_html(ok, email, error, state):
    title = "Authentication successful" if ok else "Authentication failed"
    body = (
        f"<p>Signed in as <strong>{email}</strong>. This window will close.</p>"
        if ok and email
        else f"<p>{error or 'Something went wrong.'}</p><p>You can close this tab.</p>"
    )
    payload = json.dumps(
        {
            "type": "gworkspace_oauth_done",
            "ok": ok,
            "email": email,
            "error": error,
            "state": state,
        }
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font-family:system-ui,sans-serif;padding:2rem;max-width:32rem;margin:auto;color:#0f172a}}</style>
</head><body><h2>{title}</h2>{body}
<script>
(function() {{
  var msg = {payload};
  try {{
    if (window.opener) window.opener.postMessage(msg, window.location.origin);
  }} catch (e) {{}}
  setTimeout(function() {{ window.close(); }}, msg.ok ? 1200 : 4000);
}})();
</script></body></html>"""
