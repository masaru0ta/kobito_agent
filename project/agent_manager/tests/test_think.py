"""自律思考サイクルのテスト（spec_runner.md Phase 3 準拠）"""

import json
import re
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from server.config import AgentConfig, AgentInfo
from server.runner import Message, Runner, RunResult, ThinkResult


@pytest.fixture
def runner():
    return Runner()


@pytest.fixture
def agents_dir(tmp_path):
    d = tmp_path / "agents"
    d.mkdir()
    return d


@pytest.fixture
def agent_dir(agents_dir):
    """mission.md あり、task.md なしのエージェントディレクトリ"""
    d = agents_dir / "adam"
    d.mkdir()
    (d / "config.yaml").write_text("name: アダム\nmodel: claude-sonnet-4-20250514\n", encoding="utf-8")
    (d / "CLAUDE.md").write_text("あなたはアダム。", encoding="utf-8")
    (d / "mission.md").write_text("このシステムを設計し、構築する。", encoding="utf-8")
    return d


@pytest.fixture
def agent_info():
    return AgentInfo(
        agent_id="adam",
        config=AgentConfig(name="アダム", model="claude-sonnet-4-20250514"),
        system_prompt="あなたはアダム。",
        mission="このシステムを設計し、構築する。",
        task="- [ ] テスト項目1\n- [ ] テスト項目2",
    )


@pytest.fixture
def agent_info_no_mission():
    return AgentInfo(
        agent_id="adam",
        config=AgentConfig(name="アダム", model="claude-sonnet-4-20250514"),
        system_prompt="あなたはアダム。",
        mission=None,
        task=None,
    )


TEST_SESSION_ID = "think-session-1234"


def _make_stream_output(text, session_id=TEST_SESSION_ID):
    """claude -p --output-format stream-json の出力を模倣"""
    result_line = json.dumps({
        "type": "result", "subtype": "success",
        "result": text, "session_id": session_id,
    })
    return f"{result_line}\n"


def _mock_subprocess_run(text, session_id=TEST_SESSION_ID):
    """subprocess.run のモックを返す"""
    output = _make_stream_output(text, session_id)

    def mock_run(cmd, **kwargs):
        m = MagicMock()
        m.returncode = 0
        m.stdout = output.encode("utf-8")
        m.stderr = b""
        return m

    return mock_run


# ============================================================
# mission.md / task.md の管理
# ============================================================


class TestEnsureMission:
    """mission.md の読み込み・生成テスト"""

    async def test_reads_existing_mission(self, runner, agent_dir):
        """mission.md が存在する場合、正しく読み込める"""
        agent_info = AgentInfo(
            agent_id="adam",
            config=AgentConfig(name="アダム", model="claude-sonnet-4-20250514"),
            system_prompt="あなたはアダム。",
            mission="このシステムを設計し、構築する。",
            task=None,
        )
        result = await runner._ensure_mission(agent_info, agent_dir)
        assert result == "このシステムを設計し、構築する。"

    async def test_generates_mission_when_missing(self, runner, agent_dir):
        """mission.md が存在しない場合、LLMで生成して保存する"""
        agent_info = AgentInfo(
            agent_id="adam",
            config=AgentConfig(name="アダム", model="claude-sonnet-4-20250514"),
            system_prompt="あなたはアダム。",
            mission=None,
            task=None,
        )
        generated_mission = "# ミッション\n自律システムを構築する。"

        with patch("subprocess.run", side_effect=_mock_subprocess_run(generated_mission)):
            result = await runner._ensure_mission(agent_info, agent_dir)

        assert result == generated_mission
        assert (agent_dir / "mission.md").read_text(encoding="utf-8") == generated_mission


class TestEnsureTask:
    """task.md の読み込み・生成テスト"""

    async def test_reads_existing_task(self, runner, agent_dir):
        """task.md が存在する場合、正しく読み込める"""
        (agent_dir / "task.md").write_text("- [ ] タスク1", encoding="utf-8")
        agent_info = AgentInfo(
            agent_id="adam",
            config=AgentConfig(name="アダム", model="claude-sonnet-4-20250514"),
            system_prompt="あなたはアダム。",
            mission="ミッション",
            task="- [ ] タスク1",
        )
        result = await runner._ensure_task(agent_info, agent_dir, "ミッション")
        assert result == "- [ ] タスク1"

    async def test_generates_task_when_missing(self, runner, agent_dir):
        """task.md が存在しない場合、LLMで生成して保存する"""
        agent_info = AgentInfo(
            agent_id="adam",
            config=AgentConfig(name="アダム", model="claude-sonnet-4-20250514"),
            system_prompt="あなたはアダム。",
            mission="ミッション",
            task=None,
        )
        generated_task = "- [ ] タスク1\n- [ ] タスク2"

        with patch("subprocess.run", side_effect=_mock_subprocess_run(generated_task)):
            result = await runner._ensure_task(agent_info, agent_dir, "ミッション")

        assert result == generated_task
        assert (agent_dir / "task.md").read_text(encoding="utf-8") == generated_task


# ============================================================
# プロンプト組み立て
# ============================================================


class TestBuildThinkPrompt:
    """自律思考プロンプト組み立てのテスト"""

    def test_includes_mission(self, runner):
        """自律思考プロンプトに mission.md の内容が含まれる"""
        prompt = runner._build_think_prompt("ミッション内容", "タスク内容")
        assert "ミッション内容" in prompt

    def test_includes_task(self, runner):
        """自律思考プロンプトに task.md の内容が含まれる"""
        prompt = runner._build_think_prompt("ミッション内容", "タスク内容")
        assert "タスク内容" in prompt

    def test_includes_file_operation_instructions(self, runner):
        """自律思考プロンプトにファイル操作の指示が含まれる"""
        prompt = runner._build_think_prompt("ミッション", "タスク")
        assert "task.md" in prompt
        assert "output/" in prompt


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


# ============================================================
# think() の統合テスト
# ============================================================


class TestThink:
    """think() 統合テスト"""

    async def test_think_returns_think_result(self, runner, agent_dir):
        """think() が正常に ThinkResult を返す"""
        agent_info = AgentInfo(
            agent_id="adam",
            config=AgentConfig(name="アダム", model="claude-sonnet-4-20250514"),
            system_prompt="あなたはアダム。",
            mission="ミッション",
            task="- [ ] タスク1",
        )
        (agent_dir / "task.md").write_text("- [ ] タスク1", encoding="utf-8")

        response_text = "タスク1を完了しました。task.mdを更新しました。"
        with patch("subprocess.run", side_effect=_mock_subprocess_run(response_text)):
            result = await runner.think(agent_info, agent_dir)

        assert isinstance(result, ThinkResult)
        assert result.success is True
        assert result.agent_id == "adam"
        assert result.response == response_text
        assert result.error is None

    async def test_think_returns_result_on_error(self, runner, agent_dir):
        """think() でエラーが発生しても ThinkResult を返す（success=false）"""
        agent_info = AgentInfo(
            agent_id="adam",
            config=AgentConfig(name="アダム", model="claude-sonnet-4-20250514"),
            system_prompt="あなたはアダム。",
            mission="ミッション",
            task="- [ ] タスク1",
        )
        (agent_dir / "task.md").write_text("- [ ] タスク1", encoding="utf-8")

        # claude -p がエラーを返す
        def mock_run_error(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 1
            m.stdout = b""
            m.stderr = b"API Error"
            return m

        with patch("subprocess.run", side_effect=mock_run_error):
            result = await runner.think(agent_info, agent_dir)

        assert isinstance(result, ThinkResult)
        assert result.success is False
        assert result.error is not None
        assert result.log_path is not None
