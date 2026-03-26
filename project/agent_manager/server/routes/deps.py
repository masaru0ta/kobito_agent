"""共通依存性 — エージェント取得・パス検証"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Request

from server.config import AgentInfo, AgentNotFoundError


def _get_config_manager(request: Request):
    return request.app.state.config_manager


def _get_agents_dir(request: Request) -> Path:
    return request.app.state.agents_dir


def _get_chat_manager(request: Request):
    return request.app.state.chat_manager


def _get_runner(request: Request):
    return request.app.state.runner


def _get_trigger_manager(request: Request):
    return request.app.state.trigger_manager


def get_agent_or_404(request: Request, agent_id: str) -> AgentInfo:
    """agent_idからAgentInfoを取得する。見つからなければ404"""
    config_manager = _get_config_manager(request)
    try:
        return config_manager.get_agent(agent_id)
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail="エージェントが見つかりません")


def safe_path(base_dir: Path, *parts: str) -> Path:
    """パストラバーサル対策付きのパス結合。base_dir配下であることを検証する"""
    joined = base_dir.joinpath(*parts).resolve()
    base_resolved = base_dir.resolve()
    if not str(joined).startswith(str(base_resolved)):
        raise HTTPException(status_code=400, detail="不正なパスです")
    return joined
