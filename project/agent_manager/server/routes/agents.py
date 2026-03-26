"""エージェント情報・設定API"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from server.config import AgentInfo, AgentNotFoundError
from server.routes.deps import (
    _get_agents_dir,
    _get_config_manager,
    get_agent_or_404,
    safe_path,
)

router = APIRouter(prefix="/api/agents", tags=["agents"])


class SaveSettingsRequest(BaseModel):
    name: str
    model: str
    description: str
    system_prompt: str
    trigger_cron: str | None = None
    trigger_enabled: bool = False


class UpdateConfigRequest(BaseModel):
    name: str
    model: str
    description: str


class UpdateContentRequest(BaseModel):
    content: str


# --- 一覧・詳細 ---

@router.get("")
def list_agents(request: Request):
    cm = _get_config_manager(request)
    return [agent.model_dump() for agent in cm.list_agents()]


@router.get("/{agent_id}")
def get_agent(agent: AgentInfo = Depends(get_agent_or_404)):
    return agent.model_dump()


# --- 設定一括保存 ---

@router.put("/{agent_id}/settings")
def save_settings(agent_id: str, req: SaveSettingsRequest, request: Request,
                  agent: AgentInfo = Depends(get_agent_or_404)):
    cm = _get_config_manager(request)
    try:
        cm.save_settings(
            agent_id, req.name, req.model, req.description,
            req.system_prompt, req.trigger_cron, req.trigger_enabled,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return cm.get_agent(agent_id).model_dump()


# --- 個別更新 ---

@router.put("/{agent_id}/config")
def update_config(agent_id: str, req: UpdateConfigRequest, request: Request,
                  agent: AgentInfo = Depends(get_agent_or_404)):
    cm = _get_config_manager(request)
    try:
        result = cm.update_config(agent_id, req.name, req.model, req.description)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"agent_id": agent_id, "config": result.model_dump()}

@router.put("/{agent_id}/system-prompt")
def update_system_prompt(agent_id: str, req: UpdateContentRequest, request: Request,
                         agent: AgentInfo = Depends(get_agent_or_404)):
    cm = _get_config_manager(request)
    cm.update_system_prompt(agent_id, req.content)
    return {"agent_id": agent_id, "content": req.content}


@router.put("/{agent_id}/mission")
def update_mission(agent_id: str, req: UpdateContentRequest, request: Request,
                   agent: AgentInfo = Depends(get_agent_or_404)):
    agents_dir = _get_agents_dir(request)
    path = safe_path(agents_dir, agent_id, "mission.md")
    path.write_text(req.content, encoding="utf-8")
    return {"agent_id": agent_id, "content": req.content}


@router.put("/{agent_id}/task")
def update_task(agent_id: str, req: UpdateContentRequest, request: Request,
                agent: AgentInfo = Depends(get_agent_or_404)):
    agents_dir = _get_agents_dir(request)
    path = safe_path(agents_dir, agent_id, "task.md")
    path.write_text(req.content, encoding="utf-8")
    return {"agent_id": agent_id, "content": req.content}
