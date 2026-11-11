"""FastAPI application factory and dashboard server entry."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ribhus import __version__
from ribhus.bots.chat_store import ChatStore
from ribhus.bots.queue import BotQueueManager
from ribhus.bots.runner import BotOrchestrator
from ribhus.bots.store import BotStore
from ribhus.config import get_settings
from ribhus.web.auth import get_session_token
from ribhus.web.deps import resolve_web_dist, resolve_web_root
from ribhus.web.routers import (
    bots,
    channels,
    chats,
    config,
    mcp,
    memory,
    research,
    skills,
    tasks,
)
from ribhus.web.task_store import TaskStore


class LoopbackHostMiddleware(BaseHTTPMiddleware):
    """Reject non-loopback Host headers when binding to localhost."""

    async def dispatch(self, request: Request, call_next) -> Response:
        bind_host = getattr(request.app.state, "bind_host", "127.0.0.1")
        if bind_host in {"127.0.0.1", "localhost", "::1"}:
            host = (request.headers.get("host") or "").split(":")[0].lower()
            allowed = {
                "",
                "127.0.0.1",
                "localhost",
                "[::1]",
                "::1",
                "testserver",  # Starlette TestClient
            }
            if host and host not in allowed:
                return JSONResponse({"detail": "Host not allowed"}, status_code=403)
        return await call_next(request)


def create_app(*, task_store: TaskStore | None = None) -> FastAPI:
    settings = get_settings()
    store = task_store or TaskStore(settings.ribhus_dir / "tasks.json")
    bot_store = BotStore(settings.ribhus_dir / "bots.json")
    chat_store = ChatStore(settings.ribhus_dir / "chats.json")
    queues = BotQueueManager()
    orchestrator = BotOrchestrator(
        bots=bot_store,
        chats=chat_store,
        tasks=store,
        queues=queues,
    )
    orchestrator.ensure_direct_chats()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        queues.bind_loop(asyncio.get_running_loop())
        yield

    app = FastAPI(title="Ribhus Dashboard", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.task_store = store
    app.state.bot_store = bot_store
    app.state.chat_store = chat_store
    app.state.bot_queues = queues
    app.state.bot_orchestrator = orchestrator
    app.state.bind_host = "127.0.0.1"
    app.add_middleware(LoopbackHostMiddleware)

    app.include_router(tasks.router)
    app.include_router(bots.router)
    app.include_router(chats.router)
    app.include_router(skills.router)
    app.include_router(memory.router)
    app.include_router(channels.router)
    app.include_router(mcp.router)
    app.include_router(config.router)
    app.include_router(research.router)

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {"ok": True, "version": __version__}

    dist = resolve_web_dist()
    if dist is not None:
        index_path = dist / "index.html"

        @app.get("/")
        async def spa_index() -> HTMLResponse:
            return _inject_token(index_path.read_text(encoding="utf-8"))

        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str) -> HTMLResponse:
            # Don't swallow API routes (already registered).
            if full_path.startswith("api/"):
                return JSONResponse({"detail": "Not found"}, status_code=404)
            candidate = dist / full_path
            if candidate.is_file() and dist in candidate.resolve().parents:
                # Static non-asset file (favicon, etc.)
                from fastapi.responses import FileResponse

                return FileResponse(candidate)  # type: ignore[return-value]
            return _inject_token(index_path.read_text(encoding="utf-8"))
    else:

        @app.get("/")
        async def missing_spa() -> HTMLResponse:
            token = get_session_token()
            return HTMLResponse(
                f"""<!doctype html><html><body style="font-family:monospace;background:#0e0d0c;color:#f3efe6;padding:2rem">
                <h1>Ribhus dashboard</h1>
                <p>SPA not built. From the repo root run:</p>
                <pre>cd web && npm install && npm run build</pre>
                <p>Then restart <code>ribhus dashboard</code>.</p>
                <p>API health: <a href="/api/health" style="color:#d4a574">/api/health</a></p>
                <script>window.__RIBHUS_SESSION_TOKEN__="{token}";</script>
                </body></html>"""
            )

    return app


def _inject_token(html: str) -> HTMLResponse:
    token = get_session_token()
    snippet = f'<script>window.__RIBHUS_SESSION_TOKEN__="{token}";</script>'
    if "</head>" in html:
        html = html.replace("</head>", f"{snippet}</head>", 1)
    else:
        html = snippet + html
    return HTMLResponse(html)


def ensure_web_build(*, force: bool = False) -> Path | None:
    """Build the SPA if dist is missing. Returns dist path or None."""
    dist = resolve_web_dist()
    if dist is not None and not force:
        return dist
    try:
        web_root = resolve_web_root()
    except FileNotFoundError:
        return None
    npm = _which_npm()
    if npm is None:
        return resolve_web_dist()
    subprocess.run([npm, "install"], cwd=web_root, check=False)
    result = subprocess.run([npm, "run", "build"], cwd=web_root, check=False)
    if result.returncode != 0:
        return resolve_web_dist()
    return resolve_web_dist()


def _which_npm() -> str | None:
    from shutil import which

    return which("npm")


def start_dashboard(
    *,
    host: str = "127.0.0.1",
    port: int = 8742,
    open_browser: bool = True,
    build: bool = True,
) -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit(
            "Dashboard dependencies missing. Install with:\n"
            "  uv sync --extra dashboard\n"
            "or: pip install 'ribhus[dashboard]'"
        ) from exc

    if build:
        ensure_web_build()

    app = create_app()
    app.state.bind_host = host
    token = get_session_token()
    url = f"http://{host}:{port}/?token={token}"
    # Also allow Authorization; token query helps first load before inject.
    print(f"Ribhus dashboard → http://{host}:{port}/")
    print(f"Session token injected into HTML (also ?token= for API probes)")

    if open_browser and os.environ.get("RIBHUS_DASHBOARD_NO_OPEN", "").lower() not in {
        "1",
        "true",
        "yes",
    }:
        try:
            webbrowser.open(f"http://{host}:{port}/")
        except Exception:  # noqa: BLE001
            pass

    uvicorn.run(app, host=host, port=port, log_level="info")


def main(argv: list[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    host = "127.0.0.1"
    port = 8742
    open_browser = True
    i = 0
    while i < len(argv):
        if argv[i] == "--host" and i + 1 < len(argv):
            host = argv[i + 1]
            i += 2
        elif argv[i] == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1])
            i += 2
        elif argv[i] == "--no-open":
            open_browser = False
            i += 1
        else:
            i += 1
    start_dashboard(host=host, port=port, open_browser=open_browser)
