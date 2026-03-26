"""思考API"""

from __future__ import annotations

import json
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from server.config import AgentInfo
from server.runner import DEFAULT_THINK_PROMPT
from server.routes.agents import UpdateContentRequest
from server.routes.deps import (
    _get_agents_dir,
    _get_runner,
    get_agent_or_404,
    safe_path,
)

router = APIRouter(prefix="/api/agents/{agent_id}", tags=["think"])


@router.get("/think-prompt")
def get_think_prompt(agent_id: str, agent: AgentInfo = Depends(get_agent_or_404)):
    return {"agent_id": agent_id, "content": agent.think_prompt or DEFAULT_THINK_PROMPT}


@router.put("/think-prompt")
def update_think_prompt(agent_id: str, req: UpdateContentRequest, request: Request,
                        agent: AgentInfo = Depends(get_agent_or_404)):
    agents_dir = _get_agents_dir(request)
    path = safe_path(agents_dir, agent_id, "think_prompt.md")
    path.write_text(req.content, encoding="utf-8")
    return {"agent_id": agent_id, "content": req.content}


def _check_task_approval(task_path) -> str:
    """タスクファイルのステータスを確認し、承認済でなければ例外を投げる"""
    content = task_path.read_text(encoding="utf-8")
    match = re.search(r'\*\*ステータス:\s*(.+?)\*\*', content)
    status = match.group(1).strip() if match else "不明"
    if status != "承認済":
        raise HTTPException(status_code=403, detail="未承認のタスクは実行できません")
    return content


@router.post("/think")
async def post_think(agent_id: str, request: Request, resume: bool = False,
                     task: Optional[str] = None,
                     agent: AgentInfo = Depends(get_agent_or_404)):
    agents_dir = _get_agents_dir(request)
    runner = _get_runner(request)
    agent_dir = agents_dir / agent_id

    session_id = None
    task_file = None

    if task:
        # タスク指定モード
        task_path = safe_path(agents_dir, agent_id, "tasks", task)
        if not task_path.exists():
            raise HTTPException(status_code=404, detail="タスクが見つかりません")

        _check_task_approval(task_path)
        task_file = task

        # タスク単位のセッション管理
        session_file = agent_dir / f".session_{task}"
        if session_file.exists():
            session_id = session_file.read_text(encoding="utf-8").strip()
    elif resume:
        # 従来モード（タスク未指定 + resume）
        session_file = agent_dir / ".think_session_id"
        if session_file.exists():
            session_id = session_file.read_text(encoding="utf-8").strip()

    async def event_stream():
        result_session_id = None
        async for event in runner.think_stream(agent, agent_dir, session_id=session_id,
                                               task_file=task_file):
            event_type = event["type"]
            if event.get("session_id"):
                result_session_id = event["session_id"]
            if event_type in ("result", "error"):
                yield f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            else:
                yield f"event: {event_type}\ndata: {event.get('content', '')}\n\n"

        # セッションIDを保存
        if result_session_id and task:
            sf = agent_dir / f".session_{task}"
            sf.write_text(result_session_id, encoding="utf-8")
        elif result_session_id and not task:
            sf = agent_dir / ".think_session_id"
            sf.write_text(result_session_id, encoding="utf-8")

    return StreamingResponse(event_stream(), media_type="text/event-stream")
