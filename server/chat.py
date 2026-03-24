"""chatコンポーネント — ユーザー×エージェントのチャット処理"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Literal

from pydantic import BaseModel

from server.config import ConfigManager
from server.runner import Message, Runner, RunResult


class ChatEvent(BaseModel):
    type: Literal["conversation_id", "chunk", "done"]
    data: str


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    timestamp: datetime


class Conversation(BaseModel):
    conversation_id: str
    agent_id: str
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessage]


class ConversationSummary(BaseModel):
    conversation_id: str
    agent_id: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    last_message: str


class ConversationNotFoundError(Exception):
    pass


class ChatManager:
    def __init__(self, config_manager: ConfigManager, runner: Runner, agents_dir: Path):
        self._config_manager = config_manager
        self._runner = runner
        self._agents_dir = Path(agents_dir)

    def _chat_dir(self, agent_id: str) -> Path:
        d = self._agents_dir / agent_id / "chat_history"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _conv_path(self, agent_id: str, conversation_id: str) -> Path:
        return self._chat_dir(agent_id) / f"{conversation_id}.json"

    def _load_conv(self, agent_id: str, conversation_id: str) -> dict:
        path = self._conv_path(agent_id, conversation_id)
        if not path.exists():
            raise ConversationNotFoundError(f"会話 '{conversation_id}' が見つかりません")
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_conv(self, data: dict) -> None:
        path = self._conv_path(data["agent_id"], data["conversation_id"])
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    async def send_message(
        self,
        agent_id: str,
        conversation_id: str | None,
        message: str,
    ) -> AsyncGenerator[ChatEvent, None]:
        """メッセージを送信し、応答をストリーミングで返す"""
        if not message:
            raise ValueError("メッセージが空です")

        # エージェント存在確認
        agent_info = self._config_manager.get_agent(agent_id)

        now = datetime.now(timezone.utc).isoformat()
        is_new = conversation_id is None

        if is_new:
            conversation_id = str(uuid.uuid4())
            conv_data = {
                "conversation_id": conversation_id,
                "agent_id": agent_id,
                "created_at": now,
                "updated_at": now,
                "session_id": None,
                "messages": [],
            }
            yield ChatEvent(type="conversation_id", data=conversation_id)
        else:
            conv_data = self._load_conv(agent_id, conversation_id)

        # Claude Codeのセッションを継続（session_idがあれば--resume）
        session_id = conv_data.get("session_id")
        messages = [Message(role="user", content=message)]

        # ストリーミング応答
        full_response = ""
        run_result = None
        async for item in self._runner.run_stream(agent_info, messages, session_id):
            if isinstance(item, RunResult):
                run_result = item
            else:
                full_response += item
                yield ChatEvent(type="chunk", data=item)

        yield ChatEvent(type="done", data=full_response)

        # session_idを保存（初回は新規取得、継続時は更新）
        if run_result and run_result.session_id:
            conv_data["session_id"] = run_result.session_id

        # 会話履歴に保存
        conv_data["messages"].append({"role": "user", "content": message, "timestamp": now})
        conv_data["messages"].append({"role": "assistant", "content": full_response, "timestamp": now})
        conv_data["updated_at"] = now
        self._save_conv(conv_data)

    def get_conversations(self, agent_id: str) -> list[ConversationSummary]:
        """エージェントの会話一覧を返す（新しい順）"""
        chat_dir = self._chat_dir(agent_id)
        summaries = []

        for path in chat_dir.glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            messages = data.get("messages", [])
            last_msg = messages[-1]["content"] if messages else ""

            summaries.append(
                ConversationSummary(
                    conversation_id=data["conversation_id"],
                    agent_id=data["agent_id"],
                    created_at=data["created_at"],
                    updated_at=data["updated_at"],
                    message_count=len(messages),
                    last_message=last_msg[:100],
                )
            )

        summaries.sort(key=lambda s: s.updated_at, reverse=True)
        return summaries

    def get_history(self, agent_id: str, conversation_id: str) -> Conversation:
        """指定会話の全履歴を返す"""
        data = self._load_conv(agent_id, conversation_id)
        return Conversation(
            conversation_id=data["conversation_id"],
            agent_id=data["agent_id"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            messages=[
                ChatMessage(role=m["role"], content=m["content"], timestamp=m["timestamp"])
                for m in data["messages"]
            ],
        )

    def delete_conversation(self, agent_id: str, conversation_id: str) -> None:
        """会話を削除する"""
        path = self._conv_path(agent_id, conversation_id)
        if not path.exists():
            raise ConversationNotFoundError(f"会話 '{conversation_id}' が見つかりません")
        path.unlink()
