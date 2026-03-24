"""configコンポーネントのテスト（spec_config.md準拠）"""

import pytest
import yaml

from server.config import AgentNotFoundError, ConfigManager


# ============================================================
# config読み込み
# ============================================================


class TestConfigLoad:
    """有効なconfig.yamlの読み込みテスト"""

    def test_valid_config(self, agents_dir, adam_dir):
        """有効なconfig.yamlを読み込み、AgentConfigが正しく生成される"""
        manager = ConfigManager(agents_dir)
        agent = manager.get_agent("adam")

        assert agent.agent_id == "adam"
        assert agent.config.name == "アダム"
        assert agent.config.model == "claude-sonnet-4-20250514"
        assert agent.config.description == "システムの設計者であり管理者"

    def test_system_prompt_exists(self, agents_dir, adam_dir):
        """CLAUDE.mdが存在する場合、system_promptに内容が設定される"""
        manager = ConfigManager(agents_dir)
        agent = manager.get_agent("adam")

        assert agent.system_prompt == "あなたはアダム。このシステムの設計者である。"

    def test_system_prompt_missing(self, agents_dir, eden_dir):
        """CLAUDE.mdが存在しない場合、system_promptが空文字列になる"""
        manager = ConfigManager(agents_dir)
        agent = manager.get_agent("eden")

        assert agent.system_prompt == ""

    def test_mission_exists(self, agents_dir, adam_dir):
        """mission.mdが存在する場合、missionに内容が設定される"""
        manager = ConfigManager(agents_dir)
        agent = manager.get_agent("adam")

        assert agent.mission == "このシステムを設計し、構築し、改善する。"

    def test_mission_missing(self, agents_dir, eden_dir):
        """mission.mdが存在しない場合、missionがNoneになる"""
        manager = ConfigManager(agents_dir)
        agent = manager.get_agent("eden")

        assert agent.mission is None

    def test_task_exists(self, agents_dir, adam_dir):
        """task.mdが存在する場合、taskに内容が設定される"""
        (adam_dir / "task.md").write_text("Phase 1の仕様書を書く", encoding="utf-8")
        manager = ConfigManager(agents_dir)
        agent = manager.get_agent("adam")

        assert agent.task == "Phase 1の仕様書を書く"

    def test_task_missing(self, agents_dir, adam_dir):
        """task.mdが存在しない場合、taskがNoneになる"""
        manager = ConfigManager(agents_dir)
        agent = manager.get_agent("adam")

        assert agent.task is None


# ============================================================
# エージェント一覧
# ============================================================


class TestListAgents:
    """エージェント一覧取得のテスト"""

    def test_multiple_agents(self, agents_dir, adam_dir, eden_dir):
        """agents/ディレクトリに複数エージェントがある場合、全エージェントが返る"""
        manager = ConfigManager(agents_dir)
        agents = manager.list_agents()

        assert len(agents) == 2
        agent_ids = {a.agent_id for a in agents}
        assert agent_ids == {"adam", "eden"}

    def test_empty_agents_dir(self, agents_dir):
        """agents/ディレクトリが空の場合、空リストが返る"""
        manager = ConfigManager(agents_dir)
        agents = manager.list_agents()

        assert agents == []

    def test_agents_dir_not_exists(self, tmp_path):
        """agents/ディレクトリが存在しない場合、空リストが返る"""
        manager = ConfigManager(tmp_path / "nonexistent")
        agents = manager.list_agents()

        assert agents == []

    def test_dir_without_config_ignored(self, agents_dir):
        """config.yamlがないサブディレクトリは無視される"""
        (agents_dir / "no_config_agent").mkdir()
        (agents_dir / "no_config_agent" / "CLAUDE.md").write_text("test", encoding="utf-8")

        manager = ConfigManager(agents_dir)
        agents = manager.list_agents()

        assert agents == []


# ============================================================
# エラーハンドリング
# ============================================================


class TestConfigErrors:
    """エラーハンドリングのテスト"""

    def test_invalid_yaml(self, agents_dir):
        """config.yamlのYAMLが不正な場合、例外が送出される"""
        d = agents_dir / "broken"
        d.mkdir()
        (d / "config.yaml").write_text("name: [invalid yaml", encoding="utf-8")

        manager = ConfigManager(agents_dir)
        with pytest.raises(Exception):
            manager.get_agent("broken")

    def test_missing_name_field(self, agents_dir):
        """config.yamlのnameフィールドが欠落している場合、バリデーションエラーになる"""
        d = agents_dir / "noname"
        d.mkdir()
        config = {"model": "claude-sonnet-4-20250514"}
        (d / "config.yaml").write_text(yaml.dump(config), encoding="utf-8")

        manager = ConfigManager(agents_dir)
        with pytest.raises(Exception):
            manager.get_agent("noname")

    def test_missing_model_field(self, agents_dir):
        """config.yamlのmodelフィールドが欠落している場合、バリデーションエラーになる"""
        d = agents_dir / "nomodel"
        d.mkdir()
        config = {"name": "テスト"}
        (d / "config.yaml").write_text(yaml.dump(config, allow_unicode=True), encoding="utf-8")

        manager = ConfigManager(agents_dir)
        with pytest.raises(Exception):
            manager.get_agent("nomodel")

    def test_agent_not_found(self, agents_dir):
        """存在しないagent_idでget_agentを呼ぶとAgentNotFoundErrorが送出される"""
        manager = ConfigManager(agents_dir)
        with pytest.raises(AgentNotFoundError):
            manager.get_agent("nonexistent")


# ============================================================
# REST API
# ============================================================


class TestConfigAPI:
    """REST APIのテスト"""

    @pytest.fixture
    def client(self, agents_dir, adam_dir, eden_dir):
        from httpx import ASGITransport, AsyncClient

        from server.app import create_app

        app = create_app(agents_dir=agents_dir)
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test")

    async def test_get_agents(self, client):
        """GET /api/agents が200とエージェント一覧を返す"""
        resp = await client.get("/api/agents")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        agent_ids = {a["agent_id"] for a in data}
        assert agent_ids == {"adam", "eden"}

    async def test_get_agent_detail(self, client):
        """GET /api/agents/{agent_id} が200とエージェント詳細を返す"""
        resp = await client.get("/api/agents/adam")

        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == "adam"
        assert data["config"]["name"] == "アダム"
        assert data["config"]["model"] == "claude-sonnet-4-20250514"
        assert data["system_prompt"] == "あなたはアダム。このシステムの設計者である。"

    async def test_get_agent_not_found(self, client):
        """GET /api/agents/{agent_id} で存在しないIDを指定すると404を返す"""
        resp = await client.get("/api/agents/nonexistent")

        assert resp.status_code == 404
