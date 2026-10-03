from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agentgymnasium.core.schemas.challenge import ScenarioPreset, WorldTemplate
from agentgymnasium.core.schemas.setup import LaunchConfig
from agentgymnasium.services.preset_service import (
    get_scenario_preset,
    get_world_template,
    list_saved_presets,
    load_preset,
    load_scenario_presets,
    load_world_templates,
    save_preset,
)

router = APIRouter(prefix="/api", tags=["presets"])


class SavePresetRequest(BaseModel):
    name: str
    config: LaunchConfig


class SavePresetResponse(BaseModel):
    name: str
    path: str


@router.get("/presets", response_model=list[ScenarioPreset])
async def list_presets() -> list[ScenarioPreset]:
    return load_scenario_presets()


@router.get("/presets/{preset_id}", response_model=ScenarioPreset)
async def get_preset(preset_id: str) -> ScenarioPreset:
    preset = get_scenario_preset(preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"Preset not found: {preset_id}")
    return preset


@router.get("/worlds", response_model=list[WorldTemplate])
async def list_worlds() -> list[WorldTemplate]:
    return load_world_templates()


@router.get("/worlds/{template_id}", response_model=WorldTemplate)
async def get_world(template_id: str) -> WorldTemplate:
    template = get_world_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail=f"World template not found: {template_id}")
    return template


@router.post("/setup/save-preset", response_model=SavePresetResponse)
async def save_custom_preset(request: SavePresetRequest) -> SavePresetResponse:
    path = save_preset(request.name, request.config)
    return SavePresetResponse(name=request.name, path=path)


@router.get("/setup/presets", response_model=list[str])
async def list_custom_presets() -> list[str]:
    return list_saved_presets()


@router.get("/setup/presets/{name}", response_model=LaunchConfig)
async def get_custom_preset(name: str) -> LaunchConfig:
    config = load_preset(name)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Saved preset not found: {name}")
    return config
