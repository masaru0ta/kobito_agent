"""Webサーバー — FastAPIアプリケーション"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from server.chat import ChatManager, ConversationNotFoundError
from server.config import AgentNotFoundError, ConfigManager
from server.runner import Runner


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class LaunchCLIRequest(BaseModel):
    session_id: str | None = None


class UpdateConfigRequest(BaseModel):
    name: str
    model: str
    description: str


class UpdateSystemPromptRequest(BaseModel):
    content: str


def create_app(agents_dir: Path | None = None, runner: Runner | None = None) -> FastAPI:
    if agents_dir is None:
        # server/app.py → agent_manager → project → リポジトリルート → agent/
        agents_dir = Path(__file__).resolve().parent.parent.parent.parent / "agent"
    if runner is None:
        runner = Runner()

    app = FastAPI(title="kobito_agent")
    config_manager = ConfigManager(agents_dir)
    chat_manager = ChatManager(config_manager, runner, agents_dir)

    # --- config API ---

    @app.get("/api/agents")
    def list_agents():
        return [agent.model_dump() for agent in config_manager.list_agents()]

    @app.get("/api/agents/{agent_id}")
    def get_agent(agent_id: str):
        try:
            return config_manager.get_agent(agent_id).model_dump()
        except AgentNotFoundError:
            raise HTTPException(status_code=404, detail="エージェントが見つかりません")

    # --- settings API ---

    @app.put("/api/agents/{agent_id}/config")
    def update_config(agent_id: str, req: UpdateConfigRequest):
        try:
            result = config_manager.update_config(agent_id, req.name, req.model, req.description)
        except AgentNotFoundError:
            raise HTTPException(status_code=404, detail="エージェントが見つかりません")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"agent_id": agent_id, "config": result.model_dump()}

    @app.put("/api/agents/{agent_id}/system-prompt")
    def update_system_prompt(agent_id: str, req: UpdateSystemPromptRequest):
        try:
            config_manager.update_system_prompt(agent_id, req.content)
        except AgentNotFoundError:
            raise HTTPException(status_code=404, detail="エージェントが見つかりません")
        return {"agent_id": agent_id, "content": req.content}

    # --- chat API ---

    @app.post("/api/agents/{agent_id}/chat")
    async def post_chat(agent_id: str, req: ChatRequest):
        if not req.message:
            raise HTTPException(status_code=400, detail="メッセージが空です")

        try:
            config_manager.get_agent(agent_id)
        except AgentNotFoundError:
            raise HTTPException(status_code=404, detail="エージェントが見つかりません")

        async def event_stream():
            try:
                async for event in chat_manager.send_message(agent_id, req.conversation_id, req.message):
                    data_lines = "\n".join(f"data: {line}" for line in event.data.split("\n"))
                    yield f"event: {event.type}\n{data_lines}\n\n"
            except Exception as e:
                import traceback
                err_msg = f"{type(e).__name__}: {str(e)}"
                print(f"[ERROR] {err_msg}")
                traceback.print_exc()
                yield f"event: error\ndata: {err_msg}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/api/agents/{agent_id}/conversations")
    def get_conversations(agent_id: str):
        try:
            config_manager.get_agent(agent_id)
        except AgentNotFoundError:
            raise HTTPException(status_code=404, detail="エージェントが見つかりません")
        return [c.model_dump() for c in chat_manager.get_conversations(agent_id)]

    @app.get("/api/agents/{agent_id}/conversations/{conversation_id}")
    def get_conversation(agent_id: str, conversation_id: str):
        try:
            return chat_manager.get_history(agent_id, conversation_id).model_dump()
        except ConversationNotFoundError:
            raise HTTPException(status_code=404, detail="会話が見つかりません")

    @app.delete("/api/agents/{agent_id}/conversations/{conversation_id}", status_code=204)
    def delete_conversation(agent_id: str, conversation_id: str):
        try:
            chat_manager.delete_conversation(agent_id, conversation_id)
        except ConversationNotFoundError:
            raise HTTPException(status_code=404, detail="会話が見つかりません")

    # --- think API ---

    @app.post("/api/agents/{agent_id}/think")
    async def post_think(agent_id: str):
        try:
            agent_info = config_manager.get_agent(agent_id)
        except AgentNotFoundError:
            raise HTTPException(status_code=404, detail="エージェントが見つかりません")

        agent_dir = agents_dir / agent_id
        result = await runner.think(agent_info, agent_dir)
        return {
            "agent_id": result.agent_id,
            "response": result.response,
            "log_path": result.log_path,
            "success": result.success,
            "error": result.error,
        }

    # --- logs API ---

    @app.get("/api/agents/{agent_id}/logs")
    def get_logs(agent_id: str):
        try:
            config_manager.get_agent(agent_id)
        except AgentNotFoundError:
            raise HTTPException(status_code=404, detail="エージェントが見つかりません")

        log_dir = agents_dir / agent_id / "log"
        if not log_dir.exists():
            return []

        logs = []
        for path in sorted(log_dir.glob("*.json"), reverse=True):
            data = json.loads(path.read_text(encoding="utf-8"))
            response = data.get("response", "")
            summary = response[:100] if response else ""
            logs.append({
                "filename": path.name,
                "timestamp": data.get("timestamp"),
                "summary": summary,
                "success": data.get("success", False),
            })
        return logs

    @app.get("/api/agents/{agent_id}/logs/{filename}")
    def get_log_detail(agent_id: str, filename: str):
        try:
            config_manager.get_agent(agent_id)
        except AgentNotFoundError:
            raise HTTPException(status_code=404, detail="エージェントが見つかりません")

        log_path = agents_dir / agent_id / "log" / filename
        if not log_path.exists():
            raise HTTPException(status_code=404, detail="ログが見つかりません")

        return json.loads(log_path.read_text(encoding="utf-8"))

    # --- outputs API ---

    @app.get("/api/agents/{agent_id}/outputs")
    def get_outputs(agent_id: str):
        try:
            config_manager.get_agent(agent_id)
        except AgentNotFoundError:
            raise HTTPException(status_code=404, detail="エージェントが見つかりません")

        output_dir = agents_dir / agent_id / "output"
        if not output_dir.exists():
            return []

        outputs = []
        for path in sorted(output_dir.glob("*.md")):
            if path.name == "index.md":
                continue
            outputs.append({
                "filename": path.name,
                "size": path.stat().st_size,
            })
        return outputs

    @app.get("/api/agents/{agent_id}/outputs/{filename}")
    def get_output_content(agent_id: str, filename: str):
        try:
            config_manager.get_agent(agent_id)
        except AgentNotFoundError:
            raise HTTPException(status_code=404, detail="エージェントが見つかりません")

        output_path = agents_dir / agent_id / "output" / filename
        if not output_path.exists():
            raise HTTPException(status_code=404, detail="成果物が見つかりません")

        return {
            "filename": filename,
            "content": output_path.read_text(encoding="utf-8"),
        }

    # --- CLI起動 API ---

    @app.post("/api/agents/{agent_id}/launch-cli")
    def launch_cli(agent_id: str, req: LaunchCLIRequest):
        """エージェントのClaude CLIを新しいターミナルで起動する"""
        try:
            config_manager.get_agent(agent_id)
        except AgentNotFoundError:
            raise HTTPException(status_code=404, detail="エージェントが見つかりません")

        session_id = req.session_id
        agent_dir = agents_dir.resolve() / agent_id
        if session_id:
            cmd = f'claude --resume {session_id}'
        else:
            cmd = 'claude'

        if sys.platform == "win32":
            subprocess.Popen(
                f'start cmd /k "cd /d {agent_dir} && {cmd}"',
                shell=True,
            )
        else:
            raise HTTPException(status_code=501, detail="Linux/macOS未対応")

        return {"status": "launched", "session_id": session_id}

    # --- 静的ファイル配信（APIルートより後にマウント） ---
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
