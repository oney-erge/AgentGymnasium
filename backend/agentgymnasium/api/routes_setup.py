from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agentgymnasium.core.schemas.setup import LaunchConfig, LaunchState, ValidationResult
from agentgymnasium.services import workspace_config_service
from agentgymnasium.services.orchestrator import run_manager
from agentgymnasium.setup.validators import validate_launch_config

router = APIRouter(prefix="/api/setup", tags=["setup"])


class WorkspaceConfigStatus(BaseModel):
    path: str
    exists: bool
    mtime_ns: int | None


class WorkspaceConfigResponse(BaseModel):
    config: LaunchConfig
    path: str
    mtime_ns: int | None


class SaveWorkspaceConfigRequest(BaseModel):
    config: LaunchConfig


def _workspace_response(config: LaunchConfig, status: dict) -> WorkspaceConfigResponse:
    return WorkspaceConfigResponse(
        config=config,
        path=status["path"],
        mtime_ns=status["mtime_ns"],
    )


@router.get("/workspace-config", response_model=WorkspaceConfigResponse)
async def get_workspace_config() -> WorkspaceConfigResponse:
    try:
        config, status = workspace_config_service.load_workspace_config()
    except Exception as exc:  # noqa: BLE001 - keep invalid hand-edits visible to UI
        raise HTTPException(
            status_code=422,
            detail=f"Workspace config JSON is invalid: {exc}",
        ) from exc
    return _workspace_response(config, status)


@router.post("/workspace-config", response_model=WorkspaceConfigResponse)
async def save_workspace_config(
    request: SaveWorkspaceConfigRequest,
) -> WorkspaceConfigResponse:
    status = workspace_config_service.save_workspace_config(request.config)
    return _workspace_response(request.config, status)


@router.get("/workspace-config/status", response_model=WorkspaceConfigStatus)
async def get_workspace_config_status() -> WorkspaceConfigStatus:
    return WorkspaceConfigStatus(**workspace_config_service.workspace_config_status())


@router.post("/validate", response_model=ValidationResult)
async def validate_setup(config: LaunchConfig) -> ValidationResult:
    return await validate_launch_config(config)


@router.post("/launch")
async def launch(config: LaunchConfig) -> dict:
    # Re-validate server-side so an invalid config (e.g. a 'manual' provider, a
    # missing required field, or an offline endpoint) can't be launched by
    # bypassing the UI — it would otherwise surface only as a mid-run error.
    result = await validate_launch_config(config)
    if result.state != LaunchState.ready:
        raise HTTPException(
            status_code=422,
            detail={
                "state": result.state.value,
                "missing": result.missing,
                "warnings": result.warnings,
            },
        )
    run_id = await run_manager.create_run(config)
    return {"run_id": run_id}
