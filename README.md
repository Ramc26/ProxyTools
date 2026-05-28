# ProxyTools — Personal AI Assistant (MCP Hub)

ProxyTools is my **Personal AI Assistant** project. One AI agent can talk to many tools through a single MCP hub, instead of setting up every service separately.

I'm applying for **Swiggy Builders Club** MCP access to plug Swiggy's official MCP servers into this same setup.

---

## What I'm building

A **personal agent** that helps with day-to-day work in one place:

- **Life & productivity** — email (Gmail), calendar, web search, notes, and personal project tracking  
- **Build & ship** — GitHub repos, API testing (Postman), and my own org tools (30+ custom MCP tools on a separate server)  
- **Swiggy (with access)** — use Builders Club MCP tools for Swiggy-related workflows, experiments, and learning how product/API tools fit into a real assistant  

The idea is simple: **one assistant, many backends**. Swiggy MCP runs **in parallel** with my other MCP servers. The agent picks the right tool for the job (e.g. check calendar → search the web → open a GitHub PR → use a Swiggy tool when needed).

ProxyTools is the **glue**:

- `servers.py` — list of external MCPs (add one block = done)
- `mcp_hub.py` — mounts those servers for Cursor / Inspector
- `app.py` — FastAPI entry + web UI to browse tools
- `helper.py` — loads hub and groups tools for the UI

This repo is the **integration layer**. My full assistant also includes my own FastMCP server with org-specific tools; that stays separate but can be merged into the same hub later.

---

## Recent updates

### Agent architecture (modularized)

The agent internals are now split into a small `agents/` package:

- `agents/service.py` — session + chat orchestration
- `agents/langgraph.py` — LangGraph run loop
- `agents/crew.py` — CrewAI run loop
- `agents/tools.py` — MCP tool wrapper, tool catalog, prompt builders
- `agents/__init__.py` — exports

`agent.py` is now a thin compatibility facade so existing imports in `app.py` continue to work.

### UI modernization

The studio UI has been refreshed:

- Integration cards show provider logos (GitHub, Postman, Brave, Google, GitLab)
- Google Workspace account panel appears only when `gworkspace` is selected
- Chat activity panel is collapsible/expandable with cleaner controls
- Chat quality-of-life features: quick prompts, clear chat, copy last reply, export chat JSON
- Cleaner visual system for cards, spacing, chips, and chat surfaces

### Logging improvements

Tool logs are now grouped in clearer terminal blocks with explicit sections for:

- tool called
- input arguments
- output / error

This makes MCP debugging and tool tracing easier while running `uvicorn`.

---

## How I plan to use Swiggy Builders Club MCP

If we get access, I will:

1. **Add Swiggy MCP** to `servers.py` (same pattern as GitHub / Postman — stdio or HTTP).
2. **Mount it on the hub** so tools show up with a clear prefix (e.g. `swiggy_*`) and don't clash with Gmail, GitHub, etc.
3. **Test in MCP Inspector and Cursor** — list tools, call them safely, confirm auth and limits.
4. **Use it from my Personal AI Assistant** for Swiggy-focused tasks (explore APIs, internal tooling, hackathon-style builds — per whatever Builders Club allows).
5. **Document** what works in this README so others on the program can reproduce the setup.

I won't treat Swiggy MCP as a standalone app — it becomes **one module** in a bigger assistant that already handles search, dev tools, and (planned) Gmail/calendar/project tools.

---

## External MCP servers (working in parallel)

These run **alongside** Swiggy MCP. Each does its own job; the agent routes to the right one.

| Area | MCP / service | Status in this repo | Typical use |
|------|----------------|---------------------|-------------|
| Web search | Brave Search | ✅ Wired | Look up docs, news, answers |
| Code & repos | GitHub | ✅ Wired | PRs, files, issues |
| APIs | Postman | ✅ Wired | Collections, API workflows |
| Email | Gmail | 🔜 Planned | Read/draft mail, summaries |
| Calendar | Google Calendar | 🔜 Planned | Events, reminders, scheduling |
| Projects | Custom / Notion-style MCP | 🔜 Planned | Personal task & project tracking |
| Swiggy | Builders Club MCP | 🔜 With access | Swiggy program tools & experiments |
| My org | Separate FastMCP server | ✅ Separate | 30+ internal tools (merge into hub later) |

"Parallel" means: **one hub process**, many mounted servers. No need to restart or switch apps — the model sees all allowed tools in one list.

---

## What's in the repo today

| File | Role |
|------|------|
| `app.py` | **Start here** — web UI (`uvicorn app:app`) |
| `servers.py` | External MCP config (edit this to add servers) |
| `mcp_hub.py` | MCP hub for Cursor / Claude / Inspector |
| `helper.py` | Tool listing for the UI |
| `agent.py` | Compatibility facade (imports from `agents/`) |
| `agents/` | Agent implementation (service + framework loops + prompts/tools) |
| `templates/` | HTML UI (Studio + Agent tabs) |

**Add a server** — one entry in `servers.py`:

```python
{
    "namespace": "mytool",
    "title": "My Tool",           # optional, shown in UI
    "connection": "stdio",        # or "http"
    "package": "@scope/mcp-pkg",  # for stdio
    # "url": "https://...",       # for http
    "env_keys": ["MY_API_KEY"],
},
```

**Run the web UI**

```bash
uv sync
uv run uvicorn app:app --reload --port 8000
```

Open http://localhost:8000 → **Agent Chat** tab → select integrations (GitHub, Brave, Postman, Google Workspace, …) → **Start chat**.

Needs `OPENAI_API_KEY` in `.env` (default model: `gpt-4o-mini`, override with `OPENAI_MODEL`). Optional `OPENAI_BACKUP_MODEL` for failover. The agent only gets tools from integrations you select for that session.

**Run the MCP hub** (for AI clients)

```bash
uv run python mcp_hub.py
```

**MCP Studio (web control center)**

```bash
uv run uvicorn app:app --reload --port 8000
```

Open http://localhost:8000 — server status, test `hub_ping`, run any tool with JSON args, browse schemas.

**MCP Inspector (best for deep dev testing)**

From the project folder (needs Node.js):

```bash
npx -y @modelcontextprotocol/inspector uv run python mcp_hub.py
```

Opens a browser UI to connect to your hub, **list all tools**, and **call them** interactively (same as Cursor’s MCP debug flow).

Shortcut if you use the studio page: copy the Inspector command from the top panel.

**API (studio / scripts)**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/status` | GET | Server mount status + env |
| `/api/tools` | GET | All tools grouped |
| `/api/test/hub` | POST | Quick `hub_ping` test |
| `/api/tools/run` | POST | `{"tool_name": "hub_echo", "arguments": {"message": "hi"}}` |
| `/api/gworkspace/accounts` | GET | List authenticated / known Google accounts |
| `/api/gworkspace/auth?email=you@gmail.com` | GET | Check Google token file on disk |
| `/api/gworkspace/authenticate` | POST | `{"email": "..."}` — returns `auth_url` (opened in the studio browser tab) |
| `/api/gworkspace/oauth/callback` | GET | Google OAuth redirect (add this URI in Cloud Console) |
| `/api/gworkspace/oauth/status?state=` | GET | Poll until sign-in completes |

**Google Workspace (Gmail) auth**

Client ID/secret in `.env` is not enough. You must OAuth once per Gmail account.

**Studio UI:** On **New chat**, pick a Google account (or authenticate a new email) before starting a session with the gworkspace integration.

**Test users (External + Testing):** Mirror Google Console test users in `.env`:

```bash
GWORKSPACE_TEST_USERS=alice@company.com,bob@company.com
```

If set, only those emails can use **Authenticate**; others see an error asking the admin to add them in Google Cloud → OAuth consent screen → Test users. If unset, any email may be attempted (Google may still reject non–test users).

**Google Cloud redirect URI** (required for studio sign-in): add the URL shown when you click Authenticate, typically:

`http://127.0.0.1:8500/api/gworkspace/oauth/callback`

If you use another host/port, set `STUDIO_PUBLIC_URL=http://your-host:port` in `.env`.

Steps:

1. Delete wrong credential file if you copied `client_secret_*.json` into `~/.local/share/google-workspace-mcp/credentials/` (must be `type: "authorized_user"`, not `installed`).
2. Authenticate from the studio **New chat** page (opens Google sign-in in a tab in the same browser).
3. Use `gworkspace_manage_email` tools with the selected account.

Studio logs tool calls in the uvicorn terminal (`MCP_STUDIO_LOG=DEBUG` for more detail).

---

## GitLab integration (fine-grained PAT)

GitLab is configured as stdio MCP with `@zereight/mcp-gitlab`.

Required in `.env`:

```bash
GITLAB_TOKEN_FINE=glpat-xxxxxxxx
```

`servers.py` maps this token to the env key expected by the GitLab MCP package:

- `GITLAB_PERSONAL_ACCESS_TOKEN <- GITLAB_TOKEN_FINE`

Recommended token setup:

1. Create a **fine-grained PAT** in GitLab
2. Add **Group and project access** for your target groups/projects
3. Grant needed read permissions (at least project/repository/branch/search as needed)
4. Restart `uvicorn` after changing token values/permissions

Tip: for project-specific GitLab tools, prefer numeric project ID or full path instead of short project name.