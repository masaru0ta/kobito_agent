"""エージェント間通信API"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(tags=["inter_agent"])


class CallAgentRequest(BaseModel):
    message: str
    session_id: str | None = None
    caller_conversation_id: str | None = None
    call_depth: int = 0


@router.post("/api/agents/{from_id}/call/{to_id}")
async def call_agent(from_id: str, to_id: str, req: CallAgentRequest, request: Request):
    """エージェント間セッション呼び出し"""
    session_manager = request.app.state.session_manager

    try:
        result = await session_manager.call_agent(
            from_id=from_id,
            to_id=to_id,
            message=req.message,
            session_id=req.session_id,
            caller_conversation_id=req.caller_conversation_id,
            call_depth=req.call_depth,
        )
        return result.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
