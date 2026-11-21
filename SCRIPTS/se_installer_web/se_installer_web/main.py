"""
SE Installer Web - FastAPI + WebSocket backend for interactive installer.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

# Add parent paths for imports
REPO_ROOT = Path(__file__).resolve().parents[3]
SE_INSTALLER_ROOT = REPO_ROOT / "SE-INSTALLER"
SCRIPTS_ROOT = REPO_ROOT / "SCRIPTS"
# Must add SE-INSTALLER and SCRIPTS to path so modules are found
sys.path.insert(0, str(SE_INSTALLER_ROOT))
sys.path.insert(0, str(SCRIPTS_ROOT))
sys.path.insert(0, str(REPO_ROOT))

from se_installer.orchestrator import InstallerOrchestrator
from se_installer.components import get_all_components, get_recommended_components
from se_installer.models import InstallationPlan, ComponentType, InstallStatus, OSType


app = FastAPI(title="SE Installer Web", version="1.0.0")

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files (frontend)
STATIC_DIR = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------- Models ----------
class InstallRequest(BaseModel):
    component_ids: list[str]
    runtimes: list[str] = ["opencode"]
    dry_run: bool = False
    force: bool = False
    skip_verification: bool = False
    create_shortcuts: bool = False


class AdapterGenerateRequest(BaseModel):
    runtimes: list[str] = ["opencode"]


class UninstallRequest(BaseModel):
    interactive: bool = False
    all: bool = False
    include_untracked_se_mcps: bool = False
    remove_opencode_dir: bool = False
    purge_adapter: bool = False
    keep_opencode_jsonc: bool = False
    force: bool = False
    apply: bool = False
    dry_run: bool = True
    project: str = "."


class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass


manager = ConnectionManager()

# Global state for installation tracking
current_installation: dict[str, Any] = {
    "running": False,
    "orchestrator": None,
    "task": None,
}


# ---------- Helper Functions ----------
def get_repo_root() -> Path:
    return REPO_ROOT


def get_se_cli() -> Path:
    return REPO_ROOT / "SCRIPTS" / "se.py"


def get_se_python() -> str:
    """Get the Python interpreter from the SE-INSTALLER venv."""
    venv_py = SE_INSTALLER_ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


# ---------- API Routes ----------
@app.get("/")
async def root():
    """Serve the main HTML page."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse("<h1>SE Installer Web</h1><p>Frontend not built yet. Visit <a href='/static/index.html'>/static/index.html</a></p>")


@app.get("/api/components")
async def list_components():
    """List all available components with their status."""
    components = get_all_components()
    result = []
    for c in components:
        result.append({
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "category": c.category,
            "component_type": c.component_type.value,
            "status": c.status.value,
            "installed_version": c.installed_version,
            "requires": c.requires,
            "recommended": c.recommended,
            "install_method": c.install_method,
            "homepage": c.homepage,
            "docs_url": c.docs_url,
        })
    return {"components": result}


@app.get("/api/status")
async def get_status():
    """Get current installation status."""
    components = get_all_components()
    installed = [c for c in components if c.status == InstallStatus.SUCCESS]
    pending = [c for c in components if c.status == InstallStatus.PENDING]
    failed = [c for c in components if c.status == InstallStatus.FAILED]

    return {
        "total": len(components),
        "installed": len(installed),
        "pending": len(pending),
        "failed": len(failed),
        "installing": current_installation.get("running", False),
        "installed_components": [{"id": c.id, "name": c.name, "version": c.installed_version} for c in installed],
    }


@app.post("/api/install")
async def install_components(request: InstallRequest):
    """Start installation of selected components."""
    if current_installation.get("running"):
        raise HTTPException(status_code=409, detail="Installation already in progress")

    # Create plan
    plan = InstallationPlan()
    plan.dry_run = request.dry_run
    plan.force_reinstall = request.force
    plan.skip_verification = request.skip_verification
    plan.create_shortcuts = request.create_shortcuts

    orchestrator = InstallerOrchestrator(plan=plan, dry_run=request.dry_run)
    orchestrator.prepare_plan(request.component_ids, request.runtimes)

    # Store for progress tracking
    current_installation["running"] = True
    current_installation["orchestrator"] = orchestrator

    # Run in background
    async def run_installation():
        try:
            # Use the orchestrator with a progress callback
            def progress_cb(event: str, data: dict):
                asyncio.run_coroutine_threadsafe(
                    manager.broadcast({"event": event, "data": data}),
                    asyncio.get_event_loop()
                )

            # Create new orchestrator with callback
            orch = InstallerOrchestrator(plan=plan, dry_run=request.dry_run, progress_callback=progress_cb)
            orch.prepare_plan(request.component_ids, request.runtimes)
            success = orch.run_installation()

            # Broadcast completion
            await manager.broadcast({
                "event": "completed",
                "data": {"success": success, "summary": orch.get_summary()}
            })
        except Exception as e:
            await manager.broadcast({"event": "error", "data": {"message": str(e)}})
        finally:
            current_installation["running"] = False
            current_installation["orchestrator"] = None

    current_installation["task"] = asyncio.create_task(run_installation())

    return {"status": "started", "components": request.component_ids, "dry_run": request.dry_run}


@app.post("/api/uninstall")
async def uninstall_components(request: UninstallRequest):
    """Run uninstall/purge of SE artifacts."""
    se_cli = get_se_cli()
    py = get_se_python()

    cmd = [py, str(se_cli), "uninstall", "--project", request.project]

    if request.interactive:
        cmd += ["-i"]
    if request.all:
        cmd += ["--all"]
    if request.include_untracked_se_mcps:
        cmd += ["--include-untracked-se-mcps"]
    if request.remove_opencode_dir:
        cmd += ["--remove-opencode-dir"]
    if request.purge_adapter:
        cmd += ["--purge-adapter"]
    if request.keep_opencode_jsonc:
        cmd += ["--keep-opencode-jsonc"]
    if request.force:
        cmd += ["--force"]
    if request.apply:
        cmd += ["--apply"]
    if request.dry_run:
        cmd += ["--dry-run"]

    # Run in background and stream output
    async def run_uninstall():
        await manager.broadcast({"event": "started", "data": {"command": " ".join(cmd)}})
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(request.project),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            async for line in proc.stdout:
                await manager.broadcast({"event": "output", "data": {"line": line.decode().rstrip()}})
            await proc.wait()
            await manager.broadcast({"event": "completed", "data": {"exit_code": proc.returncode}})
        except Exception as e:
            await manager.broadcast({"event": "error", "data": {"message": str(e)}})

    asyncio.create_task(run_uninstall())
    return {"status": "started", "command": " ".join(cmd)}


@app.post("/api/adapter/generate")
async def generate_adapter(request: AdapterGenerateRequest):
    """Generate adapters for specified runtimes."""
    se_cli = get_se_cli()
    py = get_se_python()

    async def run_generate():
        await manager.broadcast({"event": "started", "data": {"command": "adapter generate"}})
        try:
            for rt in request.runtimes:
                await manager.broadcast({"event": "output", "data": {"line": f"Generating adapter for {rt}..."}})
                proc = await asyncio.create_subprocess_exec(
                    py, str(se_cli), "adapter", rt,
                    cwd=str(REPO_ROOT),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                async for line in proc.stdout:
                    await manager.broadcast({"event": "output", "data": {"line": line.decode().rstrip()}})
                await proc.wait()
            await manager.broadcast({"event": "completed", "data": {"exit_code": 0}})
        except Exception as e:
            await manager.broadcast({"event": "error", "data": {"message": str(e)}})

    asyncio.create_task(run_generate())
    return {"status": "started", "runtimes": request.runtimes}


@app.post("/api/adapter/remove")
async def remove_adapter():
    """Remove generated OpenCode adapter (.opencode/)."""
    opencode_dir = REPO_ROOT / ".opencode"
    if opencode_dir.exists():
        import shutil
        shutil.rmtree(opencode_dir)
        return {"status": "removed", "path": str(opencode_dir)}
    return {"status": "not_found", "path": str(opencode_dir)}


# ---------- WebSocket ----------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # Handle WebSocket CORS - accept all origins for local development
    origin = websocket.headers.get("origin")
    if origin:
        # For local development, accept all origins
        # In production, you'd validate against allowed origins
        pass
    
    await manager.connect(websocket)
    try:
        # Send initial status
        await websocket.send_json({"event": "connected", "data": await get_status()})
        while True:
            # Keep connection alive, listen for client messages
            msg = await websocket.receive_text()
            try:
                data = json.loads(msg)
                if data.get("type") == "ping":
                    await websocket.send_json({"event": "pong"})
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


# ---------- Model Selection API ----------
@app.get("/api/models")
async def get_models():
    """Get current model selection state, agent roster, and known model catalogue."""
    from se_installer.model_step import describe_selection, list_agents
    from se_installer.model_registry import MODEL_REGISTRY
    
    repo_root = get_repo_root()
    
    # Current selection
    selection = describe_selection(repo_root)
    
    # Agent roster
    roster = list_agents(repo_root)
    
    # Model catalogue
    catalogue = {}
    for model in MODEL_REGISTRY.models.values():
        if model.provider not in catalogue:
            catalogue[model.provider] = []
        catalogue[model.provider].append({
            "id": model.id,
            "name": model.name,
            "capabilities": [c.value for c in model.capabilities],
            "is_free": model.is_free,
            "context_window": model.context_window,
        })
    
    return {
        "selection": selection,
        "roster": roster,
        "catalogue": catalogue,
    }


class ModelApplyRequest(BaseModel):
    """One answer to the MODEL SELECTION step.

    ``global`` and ``agents`` are the model specs; an empty body means "clear",
    ``skip`` means "write nothing". Unknown fields are rejected so a typo does
    not look like an answer nobody applied.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    global_model: Optional[str] = Field(default=None, alias="global")
    agents: dict[str, Optional[str]] = Field(default_factory=dict)
    skip: bool = False


@app.post("/api/models")
async def apply_models(request: Optional[ModelApplyRequest] = None):
    """Apply a model selection from the web UI."""
    from se_installer.model_step import apply_selection, list_agents
    
    repo_root = get_repo_root()
    
    payload = request or ModelApplyRequest()
    skip = payload.skip
    global_spec = payload.global_model
    agents = payload.agents or {}
    
    if skip:
        return {
            "status": "cleared",
            "written": False,
            "errors": [],
            "adapters": [],
            "runtimes_refreshed": [],
            "message": "Model selection cleared by user",
        }
    
    # Validate roster
    roster = list_agents(repo_root)
    for agent_name in agents.keys():
        if agent_name not in roster:
            raise HTTPException(status_code=400, detail=f"Unknown agent: {agent_name}")
        spec = agents[agent_name]
        if spec and "/" not in spec:
            raise HTTPException(status_code=400, detail=f"Agent model for {agent_name} must be provider/model format")
    
    # Apply selection directly via model_step.apply_selection
    report = apply_selection(
        repo_root,
        global_spec=global_spec,
        agents=agents,
        skip=False,
        save=True,
        runtimes=["opencode"],
    )
    
    return {
        "status": report.get("status", "failed"),
        "written": report.get("written", False),
        "errors": report.get("errors", []),
        "adapters": report.get("adapters", []),
        "runtimes_refreshed": report.get("runtimes_refreshed", []),
        "selection": {
            "global": report.get("selection", {}).get("global_model"),
            "agents": {k: v.to_dict() for k, v in report.get("selection", {}).get("agents", {}).items()},
        },
    }


@app.get("/api/models")
async def get_models():
    """Get current model selection state, agent roster, and known model catalogue."""
    from se_installer.model_step import describe_selection, list_agents
    from se_installer.model_registry import MODEL_REGISTRY
    
    repo_root = get_repo_root()
    
    # Current selection
    selection = describe_selection(repo_root)
    
    # Agent roster
    roster = list_agents(repo_root)
    
    # Model catalogue
    catalogue = {}
    for model in MODEL_REGISTRY.models.values():
        if model.provider not in catalogue:
            catalogue[model.provider] = []
        catalogue[model.provider].append({
            "id": model.id,
            "name": model.name,
            "capabilities": [c.value for c in model.capabilities],
            "is_free": model.is_free,
            "context_window": model.context_window,
        })
    
    return {
        "selection": selection,
        "roster": roster,
        "catalogue": catalogue,
    }


@app.post("/api/models")
async def apply_models(request: Optional[ModelApplyRequest] = None):
    """Apply a model selection from the web UI."""
    from se_installer.model_step import apply_selection, list_agents
    from se_core.model_tui.config import resolve_agent_model
    
    repo_root = get_repo_root()
    
    payload = request or ModelApplyRequest()
    skip = payload.skip
    global_spec = payload.global_model
    agents = payload.agents or {}
    
    if skip:
        # Clear action
        load_func, _, save_model_config = _load_store()
        written = save_model_config(repo_root, None, {})
        return {
            "status": "cleared",
            "written": False,
            "errors": [],
            "adapters": [],
            "runtimes_refreshed": [],
            "message": "Model selection cleared by user",
        }
    
    # Validate roster
    roster = list_agents(repo_root)
    for agent_name in agents.keys():
        if agent_name not in list_agents(repo_root):
            raise HTTPException(status_code=400, detail=f"Unknown agent: {agent_name}")
        if agents[agent_name] and "/" not in agents[agent_name]:
            raise HTTPException(status_code=400, detail=f"Agent model for {agent_name} must be provider/model format")
    
    # Build selection
    selection = {}
    if global_spec:
        provider, _, model_id = global_spec.partition("/")
        if not model_id:
            provider, model_id = "", provider
        selection["global_model"] = f"{provider}/{model_id}" if provider and "/" not in model_id else model_id
    
    if agents:
        selection["agents"] = agents
    
    # Apply selection
    report = apply_selection(
        repo_root,
        selection,
        runtimes=["opencode"],
        save=True,
    )
    
    return {
        "status": report.get("status", "failed"),
        "written": report.get("written", False),
        "errors": report.get("errors", []),
        "adapters": report.get("adapters", []),
        "runtimes_refreshed": report.get("runtimes_refreshed", []),
        "selection": {
            "global": report.get("selection", {}).get("global_model"),
            "agents": {k: v.to_dict() for k, v in report.get("selection", {}).get("agents", {}).items()},
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")


def main():
    """Entry point for `se-installer-web` command."""
    import uvicorn
    import sys
    
    # Parse simple args
    host = "127.0.0.1"
    port = 8765
    reload = False
    
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--host" and i + 1 < len(args):
            host = args[i + 1]
            i += 2
        elif args[i] == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
            i += 2
        elif args[i] == "--reload":
            reload = True
            i += 1
        else:
            i += 1
    
    uvicorn.run(app, host=host, port=port, reload=reload, log_level="info")















