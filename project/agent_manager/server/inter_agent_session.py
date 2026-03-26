"""エージェント間セッション通信 — セッション呼び出し方式"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from server.config import ConfigManager
from server.runner import Message, Runner, RunResult


class CallResult(BaseModel):
    """エージェント間呼び出しの結果"""
    session_id: str
    response: str
    status: str  # "completed" or "error"
    from_agent_id: str
    to_agent_id: str


class InterAgentSessionManager:
    """エージェント間セッション管理"""

    def __init__(self, agents_dir: Path, config_manager: ConfigManager = None, runner: Runner = None):
        self._agents_dir = Path(agents_dir)
        self._config_manager = config_manager
        self._runner = runner

    async def call_agent(
        self, from_id: str, to_id: str,
        message: str, session_id: str | None = None,
        caller_conversation_id: str | None = None,
        call_depth: int = 0,
    ) -> CallResult:
        """
        エージェント間セッション呼び出し（同期処理）

        1. from_id, to_idのエージェント存在確認
        2. to_idのエージェントでclaude -p起動
        3. 応答を受け取る
        4. chat_historyに保存（呼び出し先 + 呼び出し元）
        5. 結果を返す
        """
        await self._validate_agents(from_id, to_id)

        # Claude Codeセッション実行（session_idがあれば継続）
        response, claude_session_id = await self._execute_claude_session(
            from_id, to_id, message, session_id, call_depth
        )

        # 呼び出し先のchat_historyに保存（Claude Codeの本物のsession_idを使用）
        self._save_chat_history(from_id, to_id, message, response, claude_session_id)

        # 呼び出し元のchat_historyに記録（指定がある場合）
        if caller_conversation_id:
            self._save_caller_record(from_id, to_id, message, response, caller_conversation_id)

        return CallResult(
            session_id=claude_session_id,
            response=response,
            status="completed",
            from_agent_id=from_id,
            to_agent_id=to_id,
        )

    async def _validate_agents(self, from_id: str, to_id: str) -> None:
        """エージェントの存在確認"""
        for agent_id in [from_id, to_id]:
            agent_dir = self._agents_dir / agent_id
            if not agent_dir.is_dir() or not (agent_dir / "config.yaml").exists():
                raise ValueError(f"エージェント '{agent_id}' が見つかりません")

    async def _execute_claude_session(
        self, from_id: str, to_id: str, message: str,
        session_id: str | None, call_depth: int = 0,
    ) -> tuple[str, str]:
        """Claude Codeセッションを実行して(応答テキスト, session_id)を返す"""
        agent_info = self._config_manager.get_agent(to_id)
        messages = [Message(role="user", content=message, source=f"agent:{from_id}")]
        extra_env = {
            "KOBITO_CALLER_AGENT_ID": to_id,
            "KOBITO_CALL_DEPTH": str(call_depth),
        }
        result = await self._runner.run(
            agent_info, messages, session_id=session_id, extra_env=extra_env,
        )
        return result.text, result.session_id

    def _save_chat_history(
        self, from_id: str, to_id: str,
        message: str, response: str, session_id: str,
    ) -> None:
        """呼び出し先のchat_historyに会話を保存する"""
        chat_dir = self._agents_dir / to_id / "chat_history"
        chat_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc).isoformat()

        # session_idで既存会話を検索
        conv_path = self._find_conversation_by_session(chat_dir, session_id)

        if conv_path:
            # 既存会話に追記
            conv_data = json.loads(conv_path.read_text(encoding="utf-8"))
        else:
            # 新規会話を作成
            conversation_id = str(uuid.uuid4())
            conv_data = {
                "conversation_id": conversation_id,
                "agent_id": to_id,
                "created_at": now,
                "updated_at": now,
                "session_id": session_id,
                "messages": [],
            }
            conv_path = chat_dir / f"{conv_data['conversation_id']}.json"

        conv_data["messages"].append({
            "role": "user",
            "content": message,
            "timestamp": now,
            "source": f"agent:{from_id}",
        })
        conv_data["messages"].append({
            "role": "assistant",
            "content": response,
            "timestamp": now,
            "source": "self",
        })
        conv_data["updated_at"] = now

        conv_path.write_text(json.dumps(conv_data, ensure_ascii=False), encoding="utf-8")

    def _save_caller_record(
        self, from_id: str, to_id: str,
        message: str, response: str,
        caller_conversation_id: str,
    ) -> None:
        """呼び出し元のchat_historyに呼び出し記録を追記する"""
        chat_dir = self._agents_dir / from_id / "chat_history"
        conv_path = chat_dir / f"{caller_conversation_id}.json"

        if not conv_path.exists():
            return

        conv_data = json.loads(conv_path.read_text(encoding="utf-8"))
        now = datetime.now(timezone.utc).isoformat()

        # 呼び出し結果をアシスタントメッセージとして追記
        conv_data["messages"].append({
            "role": "assistant",
            "content": f"[{to_id}に質問しました]\n\n> {message}\n\n[{to_id}の回答]\n\n{response}",
            "timestamp": now,
            "source": f"call:{to_id}",
        })
        conv_data["updated_at"] = now

        conv_path.write_text(json.dumps(conv_data, ensure_ascii=False), encoding="utf-8")

    def _find_conversation_by_session(self, chat_dir: Path, session_id: str) -> Path | None:
        """session_idが一致する会話ファイルを探す"""
        for path in chat_dir.glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("session_id") == session_id:
                return path
        return None

    def _generate_session_id(self) -> str:
        """セッションIDを生成する"""
        return str(uuid.uuid4())
