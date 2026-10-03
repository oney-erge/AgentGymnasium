from fastapi import APIRouter
from pydantic import BaseModel

from agentgymnasium.core.schemas.tool import ToolDefinition
from agentgymnasium.tools.registry import get_all_tools, get_tools_by_category

router = APIRouter(prefix="/api", tags=["tools"])


class ToolCategoryResponse(BaseModel):
    category: str
    tools: list[ToolDefinition]
    total: int
    enabled_count: int


class ToolsResponse(BaseModel):
    categories: list[ToolCategoryResponse]
    total: int
    enabled_total: int


@router.get("/tools", response_model=ToolsResponse)
async def list_tools() -> ToolsResponse:
    by_category = get_tools_by_category()
    all_tools = get_all_tools()

    categories = [
        ToolCategoryResponse(
            category=cat,
            tools=tools,
            total=len(tools),
            enabled_count=sum(1 for t in tools if t.enabled_by_default),
        )
        for cat, tools in by_category.items()
    ]

    return ToolsResponse(
        categories=categories,
        total=len(all_tools),
        enabled_total=sum(1 for t in all_tools if t.enabled_by_default),
    )
