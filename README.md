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

- `conflict.py` — one MCP server that **mounts** external MCPs (namespaced tools like `github_*`, `postman_*`, `brave_*`, and later `swiggy_*`)
- `app.py` + web UI — browse all tools in one screen (name, description, inputs)
- `helper.py` — load the hub and list tools for the UI

This repo is the **integration layer**. My full assistant also includes my own FastMCP server with org-specific tools; that stays separate but can be merged into the same hub later.

---

## How I plan to use Swiggy Builders Club MCP

If we get access, I will:

1. **Add Swiggy MCP** to `EXTERNAL_SERVERS` in `conflict.py` (same pattern as GitHub / Postman / Brave — stdio or HTTP, whatever Builders Club documents).
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
| `conflict.py` | MCP hub — run this for Cursor / Claude / Inspector |
| `app.py` | FastAPI + simple UI to list all tools |
| `helper.py` | Hub setup and tool grouping |
| `templates/` | Web UI |

**Run the hub**

```bash
uv sync
# .env — API keys for servers you want (see below)
uv run python conflict.py