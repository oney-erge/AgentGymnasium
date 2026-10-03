import pathlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agentgymnasium import __version__
from agentgymnasium.api.routes_agents import router as agents_router
from agentgymnasium.api.routes_embodiments import router as embodiments_router
from agentgymnasium.api.routes_experiments import router as experiments_router
from agentgymnasium.api.routes_exports import router as exports_router
from agentgymnasium.api.routes_presets import router as presets_router
from agentgymnasium.api.routes_runs import router as runs_router
from agentgymnasium.api.routes_setup import router as setup_router
from agentgymnasium.api.routes_tools import router as tools_router
from agentgymnasium.api.routes_ws import router as ws_router

app = FastAPI(title="AgentGymnasium", version=__version__)

app.include_router(setup_router)
app.include_router(tools_router)
app.include_router(presets_router)
app.include_router(agents_router)
app.include_router(runs_router)
app.include_router(exports_router)
app.include_router(experiments_router)
app.include_router(embodiments_router)
app.include_router(ws_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": __version__}


# Serve built frontend when it exists (production)
_static = pathlib.Path(__file__).parent / "static"
if _static.is_dir():
    # Mount assets (hashed filenames) as static files
    _assets = _static / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")

    # SPA fallback: serve a real file from the static root when one exists
    # (e.g. /favicon.svg, /icons.svg), otherwise return index.html so React
    # Router can handle client-side routes. Without the file check, root assets
    # referenced by index.html would be shadowed by index.html itself.
    _static_root = _static.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        if full_path:
            candidate = (_static / full_path).resolve()
            # Guard against path traversal: candidate must live under static/.
            if _static_root in candidate.parents and candidate.is_file():
                return FileResponse(str(candidate))
        return FileResponse(str(_static / "index.html"))
