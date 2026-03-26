"""エージェント間セッション通信のテスト"""

import json
import pytest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

from server.inter_agent_session import InterAgentSessionManager, CallResult

MOCK_SESSION_ID = "real-claude-session-id-1234-5678"


@pytest.fixture
def temp_agents_dir(tmp_path):
    """テスト用のエージェントディレクトリ"""
    agents_dir = tmp_path / "agent"

    # adamエージェント
    adam_dir = agents_dir / "adam"
    adam_dir.mkdir(parents=True)
    (adam_dir / "config.yaml").write_text("""
name: アダム
model: claude-sonnet-4-20250514
description: システム設計者
""")
    (adam_dir / "CLAUDE.md").write_text("あなたはアダムです。")
    (adam_dir / "chat_history").mkdir()

    # edenエージェント
    eden_dir = agents_dir / "eden"
    eden_dir.mkdir(parents=True)
    (eden_dir / "config.yaml").write_text("""
name: エデン
model: claude-sonnet-4-20250514
description: 協力者
""")
    (eden_dir / "CLAUDE.md").write_text("あなたはエデンです。")
    (eden_dir / "chat_history").mkdir()

    return agents_dir


@pytest.fixture
def session_manager(temp_agents_dir):
    """InterAgentSessionManagerのインスタンス"""
    return InterAgentSessionManager(temp_agents_dir)


def _mock_response(text, session_id=MOCK_SESSION_ID):
    """_execute_claude_sessionのモック戻り値を生成"""
    return (text, session_id)


class TestInterAgentSessionManager:
    """InterAgentSessionManagerのテストクラス"""

    @pytest.mark.asyncio
    async def test_call_agent_basic(self, session_manager):
        """基本的なエージェント呼び出しテスト"""
        mock_text = "順調に進んでいます。何か困ったことはありますか？"

        with patch.object(session_manager, '_execute_claude_session',
                         new_callable=AsyncMock,
                         return_value=_mock_response(mock_text)):
            result = await session_manager.call_agent(
                from_id="adam",
                to_id="eden",
                message="フェーズ5の進捗について教えて",
            )

            assert result.response == mock_text
            assert result.status == "completed"
            assert result.session_id == MOCK_SESSION_ID
            assert result.from_agent_id == "adam"
            assert result.to_agent_id == "eden"

    @pytest.mark.asyncio
    async def test_call_agent_with_existing_session(self, session_manager):
        """既存セッションでの継続会話テスト"""
        existing_session_id = str(uuid.uuid4())
        mock_text = "具体的にどの部分で困っていますか？"

        with patch.object(session_manager, '_execute_claude_session',
                         new_callable=AsyncMock,
                         return_value=_mock_response(mock_text, existing_session_id)):
            result = await session_manager.call_agent(
                from_id="adam",
                to_id="eden",
                message="実装で詰まっている部分があります",
                session_id=existing_session_id
            )

            assert result.session_id == existing_session_id
            assert result.response == mock_text

    @pytest.mark.asyncio
    async def test_call_nonexistent_agent(self, session_manager):
        """存在しないエージェントへの呼び出しエラーテスト"""
        with pytest.raises(ValueError, match="エージェント 'nonexistent' が見つかりません"):
            await session_manager.call_agent(
                from_id="adam",
                to_id="nonexistent",
                message="テストメッセージ"
            )

    @pytest.mark.asyncio
    async def test_call_agent_saves_chat_history(self, session_manager, temp_agents_dir):
        """呼び出し先にチャット履歴が保存されるテスト"""
        mock_text = "応答メッセージ"

        with patch.object(session_manager, '_execute_claude_session',
                         new_callable=AsyncMock,
                         return_value=_mock_response(mock_text)):
            await session_manager.call_agent(
                from_id="adam",
                to_id="eden",
                message="テストメッセージ"
            )

            eden_chat_dir = temp_agents_dir / "eden" / "chat_history"
            chat_files = list(eden_chat_dir.glob("*.json"))
            assert len(chat_files) == 1

            chat_data = json.loads(chat_files[0].read_text(encoding="utf-8"))
            # Claude Codeの本物のsession_idが保存されている
            assert chat_data["session_id"] == MOCK_SESSION_ID
            messages = chat_data["messages"]
            assert len(messages) == 2
            assert messages[0]["role"] == "user"
            assert messages[0]["content"] == "テストメッセージ"
            assert messages[0]["source"] == "agent:adam"
            assert messages[1]["role"] == "assistant"
            assert messages[1]["content"] == mock_text

    @pytest.mark.asyncio
    async def test_call_agent_does_not_save_to_caller(self, session_manager, temp_agents_dir):
        """呼び出し元にはチャット履歴が保存されないテスト"""
        with patch.object(session_manager, '_execute_claude_session',
                         new_callable=AsyncMock,
                         return_value=_mock_response("応答")):
            await session_manager.call_agent(
                from_id="adam",
                to_id="eden",
                message="テスト"
            )

            adam_chat_dir = temp_agents_dir / "adam" / "chat_history"
            chat_files = list(adam_chat_dir.glob("*.json"))
            assert len(chat_files) == 0

    @pytest.mark.asyncio
    async def test_call_agent_continues_session(self, session_manager, temp_agents_dir):
        """同一セッションでの会話継続テスト"""
        session_id = str(uuid.uuid4())

        with patch.object(session_manager, '_execute_claude_session',
                         new_callable=AsyncMock,
                         side_effect=[
                             _mock_response("応答1", session_id),
                             _mock_response("応答2", session_id),
                         ]):
            await session_manager.call_agent(
                from_id="adam", to_id="eden",
                message="質問1", session_id=session_id
            )
            await session_manager.call_agent(
                from_id="adam", to_id="eden",
                message="質問2", session_id=session_id
            )

            eden_chat_dir = temp_agents_dir / "eden" / "chat_history"
            chat_files = list(eden_chat_dir.glob("*.json"))
            assert len(chat_files) == 1

            chat_data = json.loads(chat_files[0].read_text(encoding="utf-8"))
            assert len(chat_data["messages"]) == 4
            assert chat_data["messages"][0]["content"] == "質問1"
            assert chat_data["messages"][1]["content"] == "応答1"
            assert chat_data["messages"][2]["content"] == "質問2"
            assert chat_data["messages"][3]["content"] == "応答2"

    @pytest.mark.asyncio
    async def test_call_agent_saves_caller_record(self, session_manager, temp_agents_dir):
        """caller_conversation_id指定時、呼び出し元にも記録されるテスト"""
        adam_chat_dir = temp_agents_dir / "adam" / "chat_history"
        conv_id = str(uuid.uuid4())
        conv_data = {
            "conversation_id": conv_id,
            "agent_id": "adam",
            "created_at": "2026-03-25T00:00:00Z",
            "updated_at": "2026-03-25T00:00:00Z",
            "session_id": None,
            "messages": [
                {"role": "user", "content": "エデンに聞いて", "timestamp": "2026-03-25T00:00:00Z", "source": "web"},
            ],
        }
        (adam_chat_dir / f"{conv_id}.json").write_text(
            json.dumps(conv_data, ensure_ascii=False), encoding="utf-8"
        )

        with patch.object(session_manager, '_execute_claude_session',
                         new_callable=AsyncMock,
                         return_value=_mock_response("めっちゃ元気やで！")):
            await session_manager.call_agent(
                from_id="adam", to_id="eden",
                message="調子どう？",
                caller_conversation_id=conv_id,
            )

            updated = json.loads((adam_chat_dir / f"{conv_id}.json").read_text(encoding="utf-8"))
            assert len(updated["messages"]) == 2
            record = updated["messages"][1]
            assert record["role"] == "assistant"
            assert record["source"] == "call:eden"
            assert "調子どう？" in record["content"]
            assert "めっちゃ元気やで！" in record["content"]

    @pytest.mark.asyncio
    async def test_call_agent_no_caller_record_without_id(self, session_manager, temp_agents_dir):
        """caller_conversation_id未指定時、呼び出し元に記録されないテスト"""
        with patch.object(session_manager, '_execute_claude_session',
                         new_callable=AsyncMock,
                         return_value=_mock_response("応答")):
            await session_manager.call_agent(
                from_id="adam", to_id="eden",
                message="テスト",
                caller_conversation_id=None,
            )

            adam_chat_dir = temp_agents_dir / "adam" / "chat_history"
            chat_files = list(adam_chat_dir.glob("*.json"))
            assert len(chat_files) == 0

    @pytest.mark.asyncio
    async def test_claude_session_execution_error(self, session_manager):
        """Claude Codeセッション実行エラーのテスト"""
        with patch.object(session_manager, '_execute_claude_session',
                         new_callable=AsyncMock, side_effect=RuntimeError("Claude実行エラー")):
            with pytest.raises(RuntimeError, match="Claude実行エラー"):
                await session_manager.call_agent(
                    from_id="adam",
                    to_id="eden",
                    message="テストメッセージ"
                )

    def test_generate_session_id(self, session_manager):
        """セッションID生成テスト"""
        session_id = session_manager._generate_session_id()

        assert isinstance(session_id, str)
        assert len(session_id) == 36
        assert session_id.count('-') == 4

    @pytest.mark.asyncio
    async def test_validate_agents_success(self, session_manager):
        """エージェント存在確認（成功）テスト"""
        await session_manager._validate_agents("adam", "eden")

    @pytest.mark.asyncio
    async def test_validate_agents_from_not_found(self, session_manager):
        """送信元エージェント存在確認（失敗）テスト"""
        with pytest.raises(ValueError, match="エージェント 'invalid' が見つかりません"):
            await session_manager._validate_agents("invalid", "eden")

    @pytest.mark.asyncio
    async def test_validate_agents_to_not_found(self, session_manager):
        """送信先エージェント存在確認（失敗）テスト"""
        with pytest.raises(ValueError, match="エージェント 'invalid' が見つかりません"):
            await session_manager._validate_agents("adam", "invalid")


class TestCallResult:
    """CallResultクラスのテスト"""

    def test_call_result_creation(self):
        """CallResult作成テスト"""
        result = CallResult(
            session_id="test-session",
            response="テスト応答",
            status="completed",
            from_agent_id="adam",
            to_agent_id="eden"
        )

        assert result.session_id == "test-session"
        assert result.response == "テスト応答"
        assert result.status == "completed"
        assert result.from_agent_id == "adam"
        assert result.to_agent_id == "eden"

    def test_call_result_model_dump(self):
        """CallResult辞書変換テスト"""
        result = CallResult(
            session_id="test-session",
            response="テスト応答",
            status="completed",
            from_agent_id="adam",
            to_agent_id="eden"
        )

        data = result.model_dump()
        expected = {
            "session_id": "test-session",
            "response": "テスト応答",
            "status": "completed",
            "from_agent_id": "adam",
            "to_agent_id": "eden"
        }

        assert data == expected
