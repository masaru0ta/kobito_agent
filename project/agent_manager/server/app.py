"""Webサーバー — FastAPIアプリケーション"""

from __future__ import annotations

import json
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from server.chat import ChatManager, ConversationNotFoundError
from server.config import AgentNotFoundError, ConfigManager
from server.runner import DEFAULT_THINK_PROMPT
from server.runner import Runner
from server.trigger import TriggerManager


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class LaunchCLIRequest(BaseModel):
    session_id: str | None = None


class TriggerToggleRequest(BaseModel):
    enabled: bool


class UpdateTriggerConfigRequest(BaseModel):
    cron: str
    enabled: bool


class UpdateConfigRequest(BaseModel):
    name: str
    model: str
    description: str


class UpdateSystemPromptRequest(BaseModel):
    content: str


class SaveSettingsRequest(BaseModel):
    name: str
    model: str
    description: str
    system_prompt: str
    trigger_cron: str | None = None
    trigger_enabled: bool = False



def create_app(agents_dir: Path | None = None, runner: Runner | None = None, config_manager: ConfigManager | None = None, trigger_manager: TriggerManager | None = None) -> FastAPI:
    if agents_dir is None:
        # server/app.py → agent_manager → project → リポジトリルート → agent/
        agents_dir = Path(__file__).resolve().parent.parent.parent.parent / "agent"
    if config_manager is None:
        config_manager = ConfigManager(agents_dir)
    if runner is None:
        runner = Runner(config_manager=config_manager)
    if trigger_manager is None:
        trigger_manager = TriggerManager(config_manager, runner, agents_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # サーバー起動時：TriggerManagerを開始
        await trigger_manager.start()
        yield
        # サーバー停止時：TriggerManagerを停止
        await trigger_manager.stop()

    app = FastAPI(title="kobito_agent", lifespan=lifespan)
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

    @app.put("/api/agents/{agent_id}/settings")
    def save_settings(agent_id: str, req: SaveSettingsRequest):
        """設定画面の全項目を一括保存する"""
        try:
            result = config_manager.save_settings(
                agent_id, req.name, req.model, req.description,
                req.system_prompt, req.trigger_cron, req.trigger_enabled,
            )
        except AgentNotFoundError:
            raise HTTPException(status_code=404, detail="エージェントが見つかりません")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return config_manager.get_agent(agent_id).model_dump()

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

    @app.put("/api/agents/{agent_id}/mission")
    def update_mission(agent_id: str, req: UpdateSystemPromptRequest):
        try:
            config_manager.get_agent(agent_id)
        except AgentNotFoundError:
            raise HTTPException(status_code=404, detail="エージェントが見つかりません")
        path = agents_dir / agent_id / "mission.md"
        path.write_text(req.content, encoding="utf-8")
        return {"agent_id": agent_id, "content": req.content}

    @app.put("/api/agents/{agent_id}/task")
    def update_task(agent_id: str, req: UpdateSystemPromptRequest):
        try:
            config_manager.get_agent(agent_id)
        except AgentNotFoundError:
            raise HTTPException(status_code=404, detail="エージェントが見つかりません")
        path = agents_dir / agent_id / "task.md"
        path.write_text(req.content, encoding="utf-8")
        return {"agent_id": agent_id, "content": req.content}

    @app.get("/api/agents/{agent_id}/think-prompt")
    def get_think_prompt(agent_id: str):
        try:
            agent_info = config_manager.get_agent(agent_id)
        except AgentNotFoundError:
            raise HTTPException(status_code=404, detail="エージェントが見つかりません")
        return {"agent_id": agent_id, "content": agent_info.think_prompt or DEFAULT_THINK_PROMPT}

    @app.put("/api/agents/{agent_id}/think-prompt")
    def update_think_prompt(agent_id: str, req: UpdateSystemPromptRequest):
        try:
            config_manager.get_agent(agent_id)
        except AgentNotFoundError:
            raise HTTPException(status_code=404, detail="エージェントが見つかりません")
        path = agents_dir / agent_id / "think_prompt.md"
        path.write_text(req.content, encoding="utf-8")
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
                err_msg = f"{type(e).__name__}: {str(e)}"
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

    @app.post("/api/agents/{agent_id}/conversations/{conversation_id}/summarize")
    async def summarize_conversation(agent_id: str, conversation_id: str):
        try:
            agent_info = config_manager.get_agent(agent_id)
        except AgentNotFoundError:
            raise HTTPException(status_code=404, detail="エージェントが見つかりません")
        try:
            result = await chat_manager.summarize(agent_id, conversation_id, agent_info, runner)
            return result
        except ConversationNotFoundError:
            raise HTTPException(status_code=404, detail="会話が見つかりません")

    # --- think API ---

    @app.post("/api/agents/{agent_id}/think")
    async def post_think(agent_id: str, resume: bool = False):
        try:
            agent_info = config_manager.get_agent(agent_id)
        except AgentNotFoundError:
            raise HTTPException(status_code=404, detail="エージェントが見つかりません")

        agent_dir = agents_dir / agent_id

        # セッション継続
        session_id = None
        if resume:
            session_file = agent_dir / ".think_session_id"
            if session_file.exists():
                session_id = session_file.read_text(encoding="utf-8").strip()

        async def event_stream():
            async for event in runner.think_stream(agent_info, agent_dir, session_id=session_id):
                event_type = event["type"]
                if event_type in ("result", "error"):
                    yield f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                else:
                    yield f"event: {event_type}\ndata: {event.get('content', '')}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

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

    # --- trigger API ---

    @app.get("/api/triggers")
    def get_triggers():
        """全エージェントのトリガー状態を返す"""
        return [status.model_dump() for status in trigger_manager.get_status()]

    @app.post("/api/agents/{agent_id}/trigger")
    async def trigger_agent_manual(agent_id: str):
        """手動でトリガーを1回発火する"""
        try:
            config_manager.get_agent(agent_id)
        except AgentNotFoundError:
            raise HTTPException(status_code=404, detail="エージェントが見つかりません")

        result = await trigger_manager.trigger_agent(agent_id)
        return {
            "agent_id": result.agent_id,
            "success": result.success,
            "response": result.response,
            "error": result.error
        }

    @app.put("/api/agents/{agent_id}/trigger")
    async def toggle_trigger(agent_id: str, req: TriggerToggleRequest):
        """トリガーの有効/無効を切り替える"""
        try:
            agent = config_manager.get_agent(agent_id)
        except AgentNotFoundError:
            raise HTTPException(status_code=404, detail="エージェントが見つかりません")

        if agent.config.trigger is None:
            raise HTTPException(status_code=400, detail="このエージェントにはトリガー設定がありません")

        result = config_manager.update_trigger_config(
            agent_id, agent.config.trigger.cron, req.enabled
        )
        return {"status": "updated", "config": result.model_dump()}

    @app.put("/api/agents/{agent_id}/trigger-config")
    async def update_trigger_config(agent_id: str, req: UpdateTriggerConfigRequest):
        """トリガー設定（cron式・有効/無効）を更新する"""
        try:
            config_manager.get_agent(agent_id)
        except AgentNotFoundError:
            raise HTTPException(status_code=404, detail="エージェントが見つかりません")

        try:
            result = config_manager.update_trigger_config(agent_id, req.cron, req.enabled)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"agent_id": agent_id, "config": result.model_dump()}

    @app.delete("/api/agents/{agent_id}/trigger-config", status_code=200)
    async def delete_trigger_config(agent_id: str):
        """トリガー設定を削除する"""
        try:
            config_manager.get_agent(agent_id)
        except AgentNotFoundError:
            raise HTTPException(status_code=404, detail="エージェントが見つかりません")

        result = config_manager.remove_trigger_config(agent_id)
        return {"agent_id": agent_id, "config": result.model_dump()}

    # --- 静的ファイル配信（APIルートより後にマウント） ---
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
