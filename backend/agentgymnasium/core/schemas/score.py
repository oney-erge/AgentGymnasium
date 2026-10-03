from __future__ import annotations

from pydantic import BaseModel


class ScoreCard(BaseModel):
    score_total: float = 0.0
    success: bool = False
    metrics: dict[str, float] = {}
    failure_events: list[dict] = []
    summary: str = ""
    reward: str = ""  # which reward function produced this
    improvement_hint: str = ""  # short deterministic "why it failed / how to improve"
