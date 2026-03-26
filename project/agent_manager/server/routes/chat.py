"""チャットAPI"""

from __future__ import annotations

import sys
import subprocess

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from server.config import AgentInfo
from server.chat import ConversationNotFoundError
from server.routes.deps import (
    _get_agents_dir,
    _get_chat_manager,
    _get_config_manager,
    _get_runner,
    get_agent_or_404,
)

router = APIRouter(prefix="/api/agents/{agent_id}", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class LaunchCLIRequest(BaseModel):
    session_id: str | None = None


@router.post("/chat")
async def post_chat(agent_id: str, req: ChatRequest, request: Request,
                    agent: AgentInfo = Depends(get_agent_or_404)):
    if not req.message:
        raise HTTPException(status_code=400, detail="メッセージが空です")

    chat_manager = _get_chat_manager(request)

    async def event_stream():
        try:
            async for event in chat_manager.send_message(agent_id, req.conversation_id, req.message):
                data_lines = "\n".join(f"data: {line}" for line in event.data.split("\n"))
                yield f"event: {event.type}\n{data_lines}\n\n"
        except Exception as e:
            err_msg = f"{type(e).__name__}: {str(e)}"
            yield f"event: error\ndata: {err_msg}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/conversations")
def get_conversations(agent_id: str, request: Request,
                      agent: AgentInfo = Depends(get_agent_or_404)):
    chat_manager = _get_chat_manager(request)
    return [c.model_dump() for c in chat_manager.get_conversations(agent_id)]


@router.get("/conversations/{conversation_id}")
def get_conversation(agent_id: str, conversation_id: str, request: Request):
    chat_manager = _get_chat_manager(request)
    try:
        return chat_manager.get_history(agent_id, conversation_id).model_dump()
    except ConversationNotFoundError:
        raise HTTPException(status_code=404, detail="会話が見つかりません")


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(agent_id: str, conversation_id: str, request: Request):
    chat_manager = _get_chat_manager(request)
    try:
        chat_manager.delete_conversation(agent_id, conversation_id)
    except ConversationNotFoundError:
        raise HTTPException(status_code=404, detail="会話が見つかりません")


@router.post("/conversations/{conversation_id}/summarize")
async def summarize_conversation(agent_id: str, conversation_id: str, request: Request,
                                 agent: AgentInfo = Depends(get_agent_or_404)):
    chat_manager = _get_chat_manager(request)
    runner = _get_runner(request)
    try:
        return await chat_manager.summarize(agent_id, conversation_id, agent, runner)
    except ConversationNotFoundError:
        raise HTTPException(status_code=404, detail="会話が見つかりません")


@router.post("/launch-cli")
def launch_cli(agent_id: str, req: LaunchCLIRequest, request: Request,
               agent: AgentInfo = Depends(get_agent_or_404)):
    """エージェントのClaude CLIを新しいターミナルで起動する"""
    agents_dir = _get_agents_dir(request)
    agent_dir = agents_dir.resolve() / agent_id

    if req.session_id:
        cmd = f'claude --resume {req.session_id}'
    else:
        cmd = 'claude'

    if sys.platform == "win32":
        subprocess.Popen(
            f'start cmd /k "cd /d {agent_dir} && {cmd}"',
            shell=True,
        )
    else:
        raise HTTPException(status_code=501, detail="Linux/macOS未対応")

    return {"status": "launched", "session_id": req.session_id}
