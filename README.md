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
| `agent.py` | RamBabu agent (OpenRouter + MCP tools) |
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

Needs `OPENROUTER_API_KEY` in `.env`. The agent only gets tools from integrations you select for that session.

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
| `/api/gworkspace/auth?email=you@gmail.com` | GET | Check Google token file on disk |

**Google Workspace (Gmail) auth**

Client ID/secret in `.env` is not enough. You must OAuth once per Gmail account:

1. Delete wrong credential file if you copied `client_secret_*.json` into `~/.local/share/google-workspace-mcp/credentials/` (must be `type: "authorized_user"`, not `installed`).
2. Run tool `gworkspace_manage_accounts` with `{"operation": "authenticate"}` (Inspector or studio).
3. Sign in in the browser, then use `gworkspace_manage_email`.

Studio logs tool calls in the uvicorn terminal (`MCP_STUDIO_LOG=DEBUG` for more detail).