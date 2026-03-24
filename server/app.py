"""Webサーバー — FastAPIアプリケーション"""

from __future__ import annotations

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


def create_app(agents_dir: Path | None = None, runner: Runner | None = None) -> FastAPI:
    if agents_dir is None:
        agents_dir = Path("agents")
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

    # --- 静的ファイル配信（APIルートより後にマウント） ---
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
