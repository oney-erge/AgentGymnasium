from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ToolCallStatus(StrEnum):
    success = "success"
    repaired = "repaired"
    rejected = "rejected"


class ToolCallRecord(BaseModel):
    ts: float  # epoch seconds
    agent_id: str
    tool: str
    args: dict = {}
    status: ToolCallStatus
    error: str | None = None
    # Defaulted so older persisted toolcalls.jsonl rows still validate.
    source: str = "agent"
    mutated: bool = False
    visual_change: bool = False
    new_body_ids: list[str] = Field(default_factory=list)
    new_joint_ids: list[str] = Field(default_factory=list)
    # Observation returned by inspection/simulation tools. Defaulted for old
    # JSONL rows and ordinary mutation tools.
    output: dict = Field(default_factory=dict)


class BuildStepRecord(BaseModel):
    """One durable Build Timeline step for a trace run."""

    attempt_index: int
    step_index: int
    trace_run_id: str | None = None
    agent_id: str
    tool: str
    status: ToolCallStatus
    label: str
    mutated: bool = False
    visual_change: bool = False
    new_body_ids: list[str] = Field(default_factory=list)
    new_joint_ids: list[str] = Field(default_factory=list)
    error: str | None = None
    trace: dict = Field(default_factory=dict)
