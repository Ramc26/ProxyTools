from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import helper

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    helper.init_hub()
    yield


app = FastAPI(title="ProxyTools", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    server: str | None = Query(None, description="Filter: hub, github, or postman"),
):
    data = await helper.get_tools_grouped(server_filter=server)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "servers": data["servers"],
            "total_tools": data["total_tools"],
            "filter": server,
        },
    )


@app.get("/api/tools")
async def api_tools(server: str | None = Query(None)):
    return await helper.get_tools_grouped(server_filter=server)
