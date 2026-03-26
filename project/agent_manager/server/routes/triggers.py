"""トリガーAPI"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from server.config import AgentInfo
from server.routes.deps import (
    _get_config_manager,
    _get_trigger_manager,
    get_agent_or_404,
)

router = APIRouter(tags=["triggers"])


class TriggerToggleRequest(BaseModel):
    enabled: bool


class UpdateTriggerConfigRequest(BaseModel):
    cron: str
    enabled: bool


@router.get("/api/triggers")
def get_triggers(request: Request):
    """全エージェントのトリガー状態を返す"""
    tm = _get_trigger_manager(request)
    return [status.model_dump() for status in tm.get_status()]


@router.post("/api/agents/{agent_id}/trigger")
async def trigger_agent_manual(agent_id: str, request: Request,
                               agent: AgentInfo = Depends(get_agent_or_404)):
    """手動でトリガーを1回発火する"""
    tm = _get_trigger_manager(request)
    result = await tm.trigger_agent(agent_id)
    return {
        "agent_id": result.agent_id,
        "success": result.success,
        "response": result.response,
        "error": result.error,
    }


@router.put("/api/agents/{agent_id}/trigger")
async def toggle_trigger(agent_id: str, req: TriggerToggleRequest, request: Request,
                         agent: AgentInfo = Depends(get_agent_or_404)):
    """トリガーの有効/無効を切り替える"""
    if agent.config.trigger is None:
        raise HTTPException(status_code=400, detail="このエージェントにはトリガー設定がありません")

    cm = _get_config_manager(request)
    result = cm.update_trigger_config(agent_id, agent.config.trigger.cron, req.enabled)
    return {"status": "updated", "config": result.model_dump()}


@router.put("/api/agents/{agent_id}/trigger-config")
async def update_trigger_config(agent_id: str, req: UpdateTriggerConfigRequest, request: Request,
                                agent: AgentInfo = Depends(get_agent_or_404)):
    """トリガー設定（cron式・有効/無効）を更新する"""
    cm = _get_config_manager(request)
    try:
        result = cm.update_trigger_config(agent_id, req.cron, req.enabled)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"agent_id": agent_id, "config": result.model_dump()}


@router.delete("/api/agents/{agent_id}/trigger-config", status_code=200)
async def delete_trigger_config(agent_id: str, request: Request,
                                agent: AgentInfo = Depends(get_agent_or_404)):
    """トリガー設定を削除する"""
    cm = _get_config_manager(request)
    result = cm.remove_trigger_config(agent_id)
    return {"agent_id": agent_id, "config": result.model_dump()}
