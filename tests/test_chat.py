"""chatコンポーネントのテスト（spec_chat.md準拠）"""

import json

import pytest

from server.chat import ChatManager
from server.config import ConfigManager


@pytest.fixture
def chat_manager(agents_dir, adam_dir, eden_dir, mock_runner):
    """ChatManagerインスタンスを返す"""
    config_manager = ConfigManager(agents_dir)
    return ChatManager(config_manager, mock_runner, agents_dir)


@pytest.fixture
def client(agents_dir, adam_dir, eden_dir, mock_runner):
    """FastAPI TestClientを返す"""
    from httpx import ASGITransport, AsyncClient

    from server.app import create_app

    app = create_app(agents_dir=agents_dir, runner=mock_runner)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ============================================================
# メッセージ送信
# ============================================================


class TestSendMessage:
    """メッセージ送信のテスト"""

    async def test_new_conversation_returns_id(self, chat_manager):
        """新規会話でメッセージを送信すると、conversation_idイベントが返る"""
        events = []
        async for event in chat_manager.send_message("adam", None, "こんにちは"):
            events.append(event)

        id_events = [e for e in events if e.type == "conversation_id"]
        assert len(id_events) == 1
        assert len(id_events[0].data) > 0

    async def test_new_conversation_returns_chunks(self, chat_manager):
        """新規会話でメッセージを送信すると、チャンクイベントが返る"""
        events = []
        async for event in chat_manager.send_message("adam", None, "こんにちは"):
            events.append(event)

        chunk_events = [e for e in events if e.type == "chunk"]
        assert len(chunk_events) == 3
        assert chunk_events[0].data == "テスト"
        assert chunk_events[1].data == "応答"
        assert chunk_events[2].data == "です。"

    async def test_new_conversation_returns_done(self, chat_manager):
        """新規会話でメッセージを送信すると、doneイベントに完全な応答が含まれる"""
        events = []
        async for event in chat_manager.send_message("adam", None, "テスト"):
            events.append(event)

        done_events = [e for e in events if e.type == "done"]
        assert len(done_events) == 1
        assert done_events[0].data == "テスト応答です。"

    async def test_existing_conversation_preserves_history(self, chat_manager, sample_conversation, mock_runner):
        """既存会話にメッセージを送信すると、会話履歴が引き継がれる"""
        events = []
        async for event in chat_manager.send_message("adam", sample_conversation, "新しいメッセージ"):
            events.append(event)

        # doneイベントがある = 正常に動作した
        done_events = [e for e in events if e.type == "done"]
        assert len(done_events) == 1

    async def test_message_saved_to_file(self, chat_manager, agents_dir):
        """送信後、会話履歴ファイルにユーザーメッセージとエージェント応答が保存される"""
        conv_id = None
        async for event in chat_manager.send_message("adam", None, "保存テスト"):
            if event.type == "conversation_id":
                conv_id = event.data

        filepath = agents_dir / "adam" / "chat_history" / f"{conv_id}.json"
        assert filepath.exists()

        data = json.loads(filepath.read_text(encoding="utf-8"))
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][0]["content"] == "保存テスト"
        assert data["messages"][1]["role"] == "assistant"
        assert data["messages"][1]["content"] == "テスト応答です。"


# ============================================================
# 会話履歴
# ============================================================


class TestConversationHistory:
    """会話履歴のテスト"""

    def test_get_history(self, chat_manager, sample_conversation):
        """get_historyで会話の全メッセージが時系列順で返る"""
        conversation = chat_manager.get_history("adam", sample_conversation)

        assert len(conversation.messages) == 2
        assert conversation.messages[0].role == "user"
        assert conversation.messages[0].content == "こんにちは"
        assert conversation.messages[1].role == "assistant"

    def test_get_conversations_newest_first(self, chat_manager, adam_dir, sample_conversation):
        """get_conversationsで会話一覧が新しい順で返る"""
        conv2 = {
            "conversation_id": "99999999-0000-0000-0000-000000000000",
            "agent_id": "adam",
            "created_at": "2026-03-25T10:00:00Z",
            "updated_at": "2026-03-25T10:00:00Z",
            "messages": [
                {"role": "user", "content": "新しい会話", "timestamp": "2026-03-25T10:00:00Z"},
            ],
        }
        filepath = adam_dir / "chat_history" / "99999999-0000-0000-0000-000000000000.json"
        filepath.write_text(json.dumps(conv2, ensure_ascii=False), encoding="utf-8")

        conversations = chat_manager.get_conversations("adam")

        assert len(conversations) == 2
        assert conversations[0].conversation_id == "99999999-0000-0000-0000-000000000000"

    def test_get_conversations_last_message(self, chat_manager, sample_conversation):
        """get_conversationsのlast_messageに最後のメッセージの先頭100文字が含まれる"""
        conversations = chat_manager.get_conversations("adam")

        assert len(conversations) == 1
        assert conversations[0].last_message.startswith("こんにちは。何かお手伝い")


# ============================================================
# 会話削除
# ============================================================


class TestDeleteConversation:
    """会話削除のテスト"""

    def test_delete_removes_file(self, chat_manager, adam_dir, sample_conversation):
        """delete_conversationで会話ファイルが削除される"""
        filepath = adam_dir / "chat_history" / f"{sample_conversation}.json"
        assert filepath.exists()

        chat_manager.delete_conversation("adam", sample_conversation)

        assert not filepath.exists()

    def test_deleted_not_in_list(self, chat_manager, sample_conversation):
        """削除後、get_conversationsの一覧に含まれない"""
        chat_manager.delete_conversation("adam", sample_conversation)
        conversations = chat_manager.get_conversations("adam")

        assert len(conversations) == 0


# ============================================================
# エラーハンドリング
# ============================================================


class TestChatErrors:
    """エラーハンドリングのテスト"""

    async def test_send_to_nonexistent_agent(self, chat_manager):
        """存在しないagent_idでメッセージ送信するとエラーになる"""
        from server.config import AgentNotFoundError

        with pytest.raises(AgentNotFoundError):
            async for _ in chat_manager.send_message("nonexistent", None, "テスト"):
                pass

    def test_get_history_nonexistent_conversation(self, chat_manager, adam_dir):
        """存在しないconversation_idで履歴取得するとエラーになる"""
        with pytest.raises(Exception):
            chat_manager.get_history("adam", "nonexistent-id")

    async def test_send_empty_message(self, chat_manager):
        """空メッセージを送信するとエラーになる"""
        with pytest.raises(ValueError):
            async for _ in chat_manager.send_message("adam", None, ""):
                pass


# ============================================================
# REST API
# ============================================================


class TestChatAPI:
    """REST APIのテスト"""

    async def test_post_chat_returns_sse(self, client):
        """POST /api/agents/{agent_id}/chat がSSEストリーミングレスポンスを返す"""
        resp = await client.post("/api/agents/adam/chat", json={"message": "こんにちは"})

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

    async def test_get_conversations(self, client, sample_conversation):
        """GET /api/agents/{agent_id}/conversations が会話一覧を返す"""
        resp = await client.get("/api/agents/adam/conversations")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1

    async def test_get_conversation_history(self, client, sample_conversation):
        """GET /api/agents/{agent_id}/conversations/{id} が会話履歴を返す"""
        resp = await client.get(f"/api/agents/adam/conversations/{sample_conversation}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["conversation_id"] == sample_conversation
        assert len(data["messages"]) == 2

    async def test_delete_conversation(self, client, sample_conversation):
        """DELETE /api/agents/{agent_id}/conversations/{id} が204を返す"""
        resp = await client.delete(f"/api/agents/adam/conversations/{sample_conversation}")

        assert resp.status_code == 204

    async def test_post_chat_nonexistent_agent(self, client):
        """存在しないagent_idへのPOSTで404が返る"""
        resp = await client.post("/api/agents/nonexistent/chat", json={"message": "テスト"})

        assert resp.status_code == 404

    async def test_get_conversation_not_found(self, client):
        """存在しないconversation_idで404が返る"""
        resp = await client.get("/api/agents/adam/conversations/nonexistent-id")

        assert resp.status_code == 404

    async def test_post_chat_empty_message(self, client):
        """空メッセージのPOSTで400が返る"""
        resp = await client.post("/api/agents/adam/chat", json={"message": ""})

        assert resp.status_code == 400
