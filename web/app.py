from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(title="PTZ Control")
app.mount("/static", StaticFiles(directory="web/static"), name="static")

templates = Jinja2Templates(directory="web/templates")


@app.get("/", response_class=HTMLResponse)
async def surface_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="surface.html", context={"active_page": "surface"})


@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="setup.html", context={"active_page": "setup"})


@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="config.html", context={"active_page": "config"})


@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="logs.html", context={"active_page": "logs"})
