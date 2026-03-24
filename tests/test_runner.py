"""runnerコンポーネントのテスト（spec_runner.md準拠）"""

import json
import subprocess
from unittest.mock import patch, MagicMock

import pytest

from server.config import AgentConfig, AgentInfo
from server.runner import Message, Runner


@pytest.fixture
def agent_info():
    """テスト用のAgentInfoを返す"""
    return AgentInfo(
        agent_id="adam",
        config=AgentConfig(
            name="アダム",
            model="claude-sonnet-4-20250514",
            description="システムの設計者であり管理者",
        ),
        system_prompt="あなたはアダム。このシステムの設計者である。",
        mission=None,
        task=None,
    )


@pytest.fixture
def agent_info_no_prompt():
    """システムプロンプトが空のAgentInfoを返す"""
    return AgentInfo(
        agent_id="empty",
        config=AgentConfig(name="テスト", model="claude-sonnet-4-20250514"),
        system_prompt="",
        mission=None,
        task=None,
    )


@pytest.fixture
def runner():
    return Runner()


def _make_stream_output(text="テスト応答です。"):
    """claude -p --output-format stream-json の出力を模倣"""
    init_line = json.dumps({"type": "system", "subtype": "init"})
    assistant_line = json.dumps({
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    })
    result_line = json.dumps({"type": "result", "subtype": "success", "result": text})
    return f"{init_line}\n{assistant_line}\n{result_line}\n"


def _mock_subprocess_run(text="テスト応答です。", returncode=0, stderr=b""):
    """subprocess.run のモックを返す"""
    output = _make_stream_output(text)

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = returncode
        result.stdout = output.encode("utf-8")
        result.stderr = stderr
        return result

    return mock_run


# ============================================================
# プロンプト組み立て
# ============================================================


class TestPromptAssembly:
    """プロンプト組み立てのテスト"""

    def test_system_prompt_at_head(self, runner, agent_info):
        """システムプロンプトがmessages配列の先頭にsystemロールで含まれる"""
        messages = [Message(role="user", content="こんにちは")]
        built = runner.build_messages(agent_info, messages)

        assert built[0]["role"] == "system"
        assert built[0]["content"] == "あなたはアダム。このシステムの設計者である。"

    def test_system_prompt_omitted_when_empty(self, runner, agent_info_no_prompt):
        """システムプロンプトが空の場合、systemメッセージが省略される"""
        messages = [Message(role="user", content="こんにちは")]
        built = runner.build_messages(agent_info_no_prompt, messages)

        assert all(m["role"] != "system" for m in built)

    def test_history_order_preserved(self, runner, agent_info):
        """会話履歴がmessages配列に正しい順序で含まれる"""
        messages = [
            Message(role="user", content="最初の質問"),
            Message(role="assistant", content="最初の回答"),
            Message(role="user", content="次の質問"),
        ]
        built = runner.build_messages(agent_info, messages)

        assert len(built) == 4
        assert built[1]["role"] == "user"
        assert built[1]["content"] == "最初の質問"
        assert built[2]["role"] == "assistant"
        assert built[2]["content"] == "最初の回答"
        assert built[3]["role"] == "user"
        assert built[3]["content"] == "次の質問"

    def test_latest_message_at_end(self, runner, agent_info):
        """最新のユーザーメッセージがmessages配列の末尾に含まれる"""
        messages = [
            Message(role="user", content="古いメッセージ"),
            Message(role="assistant", content="古い回答"),
            Message(role="user", content="最新のメッセージ"),
        ]
        built = runner.build_messages(agent_info, messages)

        assert built[-1]["role"] == "user"
        assert built[-1]["content"] == "最新のメッセージ"

    def test_single_message_returns_content_directly(self, runner):
        """メッセージが1つの場合、contentをそのまま返す"""
        messages = [Message(role="user", content="こんにちは")]
        prompt = runner._build_prompt(messages)
        assert prompt == "こんにちは"

    def test_multi_turn_prompt_has_instruction(self, runner):
        """複数ターンの場合、応答指示が含まれる"""
        messages = [
            Message(role="user", content="こんにちは"),
            Message(role="assistant", content="やあ"),
            Message(role="user", content="元気？"),
        ]
        prompt = runner._build_prompt(messages)
        assert "最後のメッセージにのみ応答" in prompt
        assert "[user]: こんにちは" in prompt
        assert "[assistant]: やあ" in prompt
        assert "[user]: 元気？" in prompt


# ============================================================
# LLM呼び出し（非ストリーミング）
# ============================================================


class TestRunNonStreaming:
    """非ストリーミングLLM呼び出しのテスト"""

    async def test_run_returns_response(self, runner, agent_info):
        """runメソッドがLLMの応答テキストを返す"""
        messages = [Message(role="user", content="こんにちは")]

        with patch("subprocess.run", side_effect=_mock_subprocess_run("こんにちは！")):
            result = await runner.run(agent_info, messages)

        assert result == "こんにちは！"

    async def test_run_uses_correct_model(self, runner, agent_info):
        """指定されたモデルIDでclaude -pが呼ばれる"""
        messages = [Message(role="user", content="テスト")]

        with patch("subprocess.run", side_effect=_mock_subprocess_run()) as mock:
            await runner.run(agent_info, messages)

        call_args = mock.call_args[0][0]
        assert "--model" in call_args
        model_idx = call_args.index("--model")
        assert call_args[model_idx + 1] == "claude-sonnet-4-20250514"

    async def test_prompt_passed_via_stdin(self, runner, agent_info):
        """プロンプトがstdin経由で渡される"""
        messages = [Message(role="user", content="テスト")]

        with patch("subprocess.run", side_effect=_mock_subprocess_run()) as mock:
            await runner.run(agent_info, messages)

        kwargs = mock.call_args[1]
        assert "input" in kwargs
        assert kwargs["input"] == "テスト".encode("utf-8")


# ============================================================
# LLM呼び出し（ストリーミング）
# ============================================================


class TestRunStreaming:
    """ストリーミングLLM呼び出しのテスト"""

    async def test_run_stream_yields_chunks(self, runner, agent_info):
        """run_streamメソッドがテキストチャンクをyieldする"""
        messages = [Message(role="user", content="こんにちは")]

        with patch("subprocess.run", side_effect=_mock_subprocess_run("こんにちは")):
            chunks = []
            async for chunk in runner.run_stream(agent_info, messages):
                chunks.append(chunk)

        assert len(chunks) > 0
        assert "".join(chunks) == "こんにちは"

    async def test_run_stream_full_response(self, runner, agent_info):
        """全チャンクを結合すると完全な応答テキストになる"""
        messages = [Message(role="user", content="テスト")]

        with patch("subprocess.run", side_effect=_mock_subprocess_run("テスト応答です。")):
            full = ""
            async for chunk in runner.run_stream(agent_info, messages):
                full += chunk

        assert full == "テスト応答です。"


# ============================================================
# エラーハンドリング
# ============================================================


class TestRunnerErrors:
    """エラーハンドリングのテスト"""

    async def test_empty_messages_raises_value_error(self, runner, agent_info):
        """空のメッセージリストでValueErrorが送出される"""
        with pytest.raises(ValueError):
            await runner.run(agent_info, [])

    async def test_llm_error_propagates(self, runner, agent_info):
        """claude -p がエラーを返した場合、例外が送出される"""
        messages = [Message(role="user", content="テスト")]

        with patch("subprocess.run", side_effect=_mock_subprocess_run(returncode=1, stderr=b"Error: API key not found")):
            with pytest.raises(RuntimeError):
                await runner.run(agent_info, messages)
