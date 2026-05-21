from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import agent
import helper

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


class ToolRunRequest(BaseModel):
    tool_name: str
    arguments: dict | None = None


class AgentSessionRequest(BaseModel):
    integrations: list[str] = []
    framework: str = "langgraph"


class AgentChatRequest(BaseModel):
    session_id: str
    message: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    helper.init_hub()
    yield


app = FastAPI(title="ProxyTools MCP Studio", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, server: str | None = Query(None)):
    data = await helper.get_studio_data(server_filter=server)
    integrations = agent.list_integrations()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "servers": data["servers"],
            "total_tools": data["total_tools"],
            "filter": server,
            "filter_options": data["filter_options"],
            "configured_servers": data["configured_servers"],
            "mount_status": data["mount_status"],
            "inspector_cmd": data["inspector_cmd"],
            "integrations": integrations,
            "frameworks": agent.list_frameworks(),
            "assistant_name": agent.ASSISTANT_NAME,
            "assistant_initials": agent.ASSISTANT_INITIALS,
        },
    )


@app.get("/api/tools")
async def api_tools(server: str | None = Query(None)):
    return await helper.get_studio_data(server_filter=server)


@app.get("/api/status")
async def api_status():
    data = await helper.get_studio_data()
    return {
        "configured_servers": data["configured_servers"],
        "mount_status": data["mount_status"],
        "total_tools": data["total_tools"],
        "inspector_cmd": data["inspector_cmd"],
    }


@app.post("/api/test/hub")
async def test_hub():
    return await helper.test_hub_ping()


@app.post("/api/tools/run")
async def run_tool(body: ToolRunRequest):
    return await helper.run_tool(body.tool_name, body.arguments)


@app.get("/api/gworkspace/auth")
async def gworkspace_auth(email: str = Query(...)):
    from studio_log import check_gworkspace_email

    return check_gworkspace_email(email)


@app.get("/api/agent/integrations")
async def agent_integrations():
    return {"integrations": agent.list_integrations()}


@app.get("/api/agent/frameworks")
async def agent_frameworks():
    return {"frameworks": agent.list_frameworks()}


@app.post("/api/agent/session")
async def agent_session(body: AgentSessionRequest):
    return agent.create_session(body.integrations, body.framework)


@app.post("/api/agent/chat")
async def agent_chat(body: AgentChatRequest):
    return await agent.chat(body.session_id, body.message.strip())
