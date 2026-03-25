"""自律思考サイクルのテスト（spec_runner.md Phase 3 準拠）"""

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from server.config import AgentConfig, AgentInfo
from server.runner import Runner, ThinkResult, DEFAULT_THINK_PROMPT


@pytest.fixture
def runner():
    return Runner()


@pytest.fixture
def agent_dir(tmp_path):
    d = tmp_path / "agent" / "adam"
    d.mkdir(parents=True)
    (d / "config.yaml").write_text("name: アダム\nmodel: claude-sonnet-4-20250514\n", encoding="utf-8")
    (d / "CLAUDE.md").write_text("あなたはアダム。", encoding="utf-8")
    (d / "mission.md").write_text("このシステムを設計し、構築する。", encoding="utf-8")
    (d / "task.md").write_text("- [ ] テスト項目1\n- [ ] テスト項目2", encoding="utf-8")
    return d


@pytest.fixture
def agent_info():
    return AgentInfo(
        agent_id="adam",
        config=AgentConfig(name="アダム", model="claude-sonnet-4-20250514"),
        system_prompt="あなたはアダム。",
        mission="このシステムを設計し、構築する。",
        task="- [ ] テスト項目1",
    )


@pytest.fixture
def agent_info_with_think_prompt():
    return AgentInfo(
        agent_id="adam",
        config=AgentConfig(name="アダム", model="claude-sonnet-4-20250514"),
        system_prompt="あなたはアダム。",
        mission="ミッション",
        task="タスク",
        think_prompt="カスタム思考プロンプト",
    )


TEST_SESSION_ID = "think-session-1234"


# ============================================================
# 思考プロンプト
# ============================================================


class TestThinkPrompt:
    """思考プロンプトの選択テスト"""

    async def test_uses_default_when_no_think_prompt(self, runner, agent_info, agent_dir):
        """think_prompt.md がない場合、デフォルトプロンプトが使われる"""
        prompts = []

        async def mock_stream(ai, prompt, **kwargs):
            prompts.append(prompt)
            yield {"type": "result", "result": "", "session_id": TEST_SESSION_ID}

        with patch.object(runner, "_run_claude_stream", mock_stream):
            async for _ in runner.think_stream(agent_info, agent_dir):
                pass

        assert prompts[0] == DEFAULT_THINK_PROMPT

    async def test_uses_custom_think_prompt(self, runner, agent_info_with_think_prompt, agent_dir):
        """think_prompt.md がある場合、その内容がプロンプトとして使われる"""
        prompts = []

        async def mock_stream(ai, prompt, **kwargs):
            prompts.append(prompt)
            yield {"type": "result", "result": "", "session_id": TEST_SESSION_ID}

        with patch.object(runner, "_run_claude_stream", mock_stream):
            async for _ in runner.think_stream(agent_info_with_think_prompt, agent_dir):
                pass

        assert prompts[0] == "カスタム思考プロンプト"

    async def test_resume_uses_short_prompt(self, runner, agent_info, agent_dir):
        """続行時は短縮プロンプトが使われる"""
        prompts = []

        async def mock_stream(ai, prompt, **kwargs):
            prompts.append(prompt)
            yield {"type": "result", "result": "", "session_id": TEST_SESSION_ID}

        with patch.object(runner, "_run_claude_stream", mock_stream):
            async for _ in runner.think_stream(agent_info, agent_dir, session_id="prev-session"):
                pass

        assert "前回の続き" in prompts[0]
        assert prompts[0] != DEFAULT_THINK_PROMPT


# ============================================================
# ストリーミング
# ============================================================


class TestThinkStream:
    """think_streamのストリーミングテスト"""

    async def test_yields_prompt_event(self, runner, agent_info, agent_dir):
        """think_stream がプロンプトイベントをyieldする"""
        async def mock_stream(ai, prompt, **kwargs):
            yield {"type": "result", "result": "", "session_id": TEST_SESSION_ID}

        with patch.object(runner, "_run_claude_stream", mock_stream):
            events = [ev async for ev in runner.think_stream(agent_info, agent_dir)]

        prompt_events = [e for e in events if e.get("type") == "prompt"]
        assert len(prompt_events) == 1
        assert prompt_events[0]["content"] == DEFAULT_THINK_PROMPT

    async def test_yields_text_events(self, runner, agent_info, agent_dir):
        """think_stream がテキストイベントをyieldする"""
        async def mock_stream(ai, prompt, **kwargs):
            yield {"type": "assistant", "message": {"content": [{"type": "text", "text": "作業中"}]}}
            yield {"type": "result", "result": "", "session_id": TEST_SESSION_ID}

        with patch.object(runner, "_run_claude_stream", mock_stream):
            events = [ev async for ev in runner.think_stream(agent_info, agent_dir)]

        text_events = [e for e in events if e.get("type") == "text"]
        assert len(text_events) == 1
        assert text_events[0]["content"] == "作業中"

    async def test_yields_tool_use_events(self, runner, agent_info, agent_dir):
        """think_stream がツール使用イベントをyieldする"""
        async def mock_stream(ai, prompt, **kwargs):
            yield {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Read", "input": {"file_path": "/path/to/task.md"}},
            ]}}
            yield {"type": "result", "result": "", "session_id": TEST_SESSION_ID}

        with patch.object(runner, "_run_claude_stream", mock_stream):
            events = [ev async for ev in runner.think_stream(agent_info, agent_dir)]

        tool_events = [e for e in events if e.get("type") == "tool_use"]
        assert len(tool_events) == 1
        assert "Read" in tool_events[0]["content"]
        assert "task.md" in tool_events[0]["content"]

    async def test_yields_result_event(self, runner, agent_info, agent_dir):
        """think_stream が結果イベントをyieldする"""
        async def mock_stream(ai, prompt, **kwargs):
            yield {"type": "assistant", "message": {"content": [{"type": "text", "text": "完了"}]}}
            yield {"type": "result", "result": "", "session_id": TEST_SESSION_ID}

        # 報告フェーズのモック
        report_call_count = 0
        original_stream = runner._run_claude_stream

        async def mock_stream_with_report(ai, prompt, **kwargs):
            nonlocal report_call_count
            report_call_count += 1
            if report_call_count == 1:
                # 作業フェーズ
                yield {"type": "assistant", "message": {"content": [{"type": "text", "text": "完了"}]}}
                yield {"type": "result", "result": "", "session_id": TEST_SESSION_ID}
            else:
                # 報告フェーズ
                yield {"type": "assistant", "message": {"content": [{"type": "text", "text": "## 報告\n- タスク完了"}]}}
                yield {"type": "result", "result": "", "session_id": TEST_SESSION_ID}

        with patch.object(runner, "_run_claude_stream", mock_stream_with_report):
            events = [ev async for ev in runner.think_stream(agent_info, agent_dir)]

        result_events = [e for e in events if e.get("type") == "result"]
        assert len(result_events) == 1
        assert result_events[0]["success"] is True

    async def test_error_yields_error_event(self, runner, agent_info, agent_dir):
        """エラー時にエラーイベントをyieldする"""
        async def mock_stream(ai, prompt, **kwargs):
            raise RuntimeError("claude -p 失敗")
            yield  # make it a generator

        with patch.object(runner, "_run_claude_stream", mock_stream):
            events = [ev async for ev in runner.think_stream(agent_info, agent_dir)]

        error_events = [e for e in events if e.get("type") == "error"]
        assert len(error_events) == 1
        assert error_events[0]["success"] is False
        assert "失敗" in error_events[0]["content"]


# ============================================================
# セッション管理
# ============================================================


class TestSessionManagement:
    """セッション管理のテスト"""

    async def test_saves_session_id(self, runner, agent_info, agent_dir):
        """session_id が .think_session_id に保存される"""
        async def mock_stream(ai, prompt, **kwargs):
            yield {"type": "result", "result": "", "session_id": TEST_SESSION_ID}

        with patch.object(runner, "_run_claude_stream", mock_stream):
            async for _ in runner.think_stream(agent_info, agent_dir):
                pass

        session_file = agent_dir / ".think_session_id"
        assert session_file.exists()
        assert session_file.read_text(encoding="utf-8") == TEST_SESSION_ID

    async def test_resume_passes_session_id(self, runner, agent_info, agent_dir):
        """続行時にsession_idが_run_claude_streamに渡される"""
        first_call_kwargs = None

        async def mock_stream(ai, prompt, **kwargs):
            nonlocal first_call_kwargs
            if first_call_kwargs is None:
                first_call_kwargs = dict(kwargs)
            yield {"type": "result", "result": "", "session_id": "new-session"}

        with patch.object(runner, "_run_claude_stream", mock_stream):
            async for _ in runner.think_stream(agent_info, agent_dir, session_id="prev-session"):
                pass

        assert first_call_kwargs.get("session_id") == "prev-session"


# ============================================================
# 思考ログ
# ============================================================


class TestSaveLog:
    """思考ログ保存のテスト"""

    def test_saves_log_file(self, runner, agent_dir):
        """ログが log/ に保存される"""
        log_data = {
            "agent_id": "adam",
            "prompt": "プロンプト",
            "response": "応答",
            "success": True,
            "error": None,
        }
        log_path = runner._save_log(agent_dir, log_data)
        assert Path(log_path).exists()

    def test_log_filename_format(self, runner, agent_dir):
        """ログファイル名が YYYYMMDD_HHMMSS.json 形式である"""
        log_data = {
            "agent_id": "adam", "prompt": "", "response": "",
            "success": True, "error": None,
        }
        log_path = runner._save_log(agent_dir, log_data)
        filename = Path(log_path).name
        assert re.match(r"\d{8}_\d{6}\.json", filename)

    def test_success_log_contains_required_fields(self, runner, agent_dir):
        """成功時のログに prompt, response が含まれる"""
        log_data = {
            "agent_id": "adam",
            "prompt": "プロンプト内容",
            "response": "LLM応答",
            "success": True,
            "error": None,
        }
        log_path = runner._save_log(agent_dir, log_data)
        saved = json.loads(Path(log_path).read_text(encoding="utf-8"))
        assert saved["prompt"] == "プロンプト内容"
        assert saved["response"] == "LLM応答"
        assert saved["success"] is True

    def test_error_log_has_error_and_false_success(self, runner, agent_dir):
        """エラー時のログに error が含まれ、success が false である"""
        log_data = {
            "agent_id": "adam",
            "prompt": "プロンプト",
            "response": "",
            "success": False,
            "error": "実行エラー",
        }
        log_path = runner._save_log(agent_dir, log_data)
        saved = json.loads(Path(log_path).read_text(encoding="utf-8"))
        assert saved["success"] is False
        assert saved["error"] == "実行エラー"

    async def test_log_contains_events(self, runner, agent_info, agent_dir):
        """ログにevents配列が含まれる"""
        async def mock_stream(ai, prompt, **kwargs):
            yield {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Read", "input": {"file_path": "task.md"}},
            ]}}
            yield {"type": "assistant", "message": {"content": [{"type": "text", "text": "完了"}]}}
            yield {"type": "result", "result": "", "session_id": TEST_SESSION_ID}

        with patch.object(runner, "_run_claude_stream", mock_stream):
            async for _ in runner.think_stream(agent_info, agent_dir):
                pass

        log_files = list((agent_dir / "log").glob("*.json"))
        assert len(log_files) >= 1
        saved = json.loads(log_files[0].read_text(encoding="utf-8"))
        assert "events" in saved
        assert len(saved["events"]) >= 2

    async def test_log_contains_session_id(self, runner, agent_info, agent_dir):
        """ログにsession_idが含まれる"""
        async def mock_stream(ai, prompt, **kwargs):
            yield {"type": "result", "result": "", "session_id": TEST_SESSION_ID}

        with patch.object(runner, "_run_claude_stream", mock_stream):
            async for _ in runner.think_stream(agent_info, agent_dir):
                pass

        log_files = list((agent_dir / "log").glob("*.json"))
        saved = json.loads(log_files[0].read_text(encoding="utf-8"))
        assert saved["session_id"] == TEST_SESSION_ID
