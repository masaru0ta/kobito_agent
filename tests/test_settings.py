"""設定管理のテスト（spec_settings.md準拠）"""

import pytest
import yaml

from server.config import AgentNotFoundError, ConfigManager


# ============================================================
# ConfigManager — update_config
# ============================================================


class TestUpdateConfig:
    """config.yaml の更新テスト"""

    def test_update_name(self, agents_dir, adam_dir):
        """update_config で config.yaml の name が更新される"""
        manager = ConfigManager(agents_dir)
        result = manager.update_config("adam", name="新アダム", model="claude-sonnet-4-20250514", description="テスト")

        assert result.name == "新アダム"
        # ファイルにも反映されている
        raw = yaml.safe_load((adam_dir / "config.yaml").read_text(encoding="utf-8"))
        assert raw["name"] == "新アダム"

    def test_update_model(self, agents_dir, adam_dir):
        """update_config で config.yaml の model が更新される"""
        manager = ConfigManager(agents_dir)
        result = manager.update_config("adam", name="アダム", model="claude-haiku-4-5-20251001", description="テスト")

        assert result.model == "claude-haiku-4-5-20251001"
        raw = yaml.safe_load((adam_dir / "config.yaml").read_text(encoding="utf-8"))
        assert raw["model"] == "claude-haiku-4-5-20251001"

    def test_update_description(self, agents_dir, adam_dir):
        """update_config で config.yaml の description が更新される"""
        manager = ConfigManager(agents_dir)
        result = manager.update_config("adam", name="アダム", model="claude-sonnet-4-20250514", description="新しい説明")

        assert result.description == "新しい説明"
        raw = yaml.safe_load((adam_dir / "config.yaml").read_text(encoding="utf-8"))
        assert raw["description"] == "新しい説明"

    def test_empty_name_raises(self, agents_dir, adam_dir):
        """update_config で name が空の場合 ValueError が送出される"""
        manager = ConfigManager(agents_dir)
        with pytest.raises(ValueError):
            manager.update_config("adam", name="", model="claude-sonnet-4-20250514", description="テスト")

    def test_empty_model_raises(self, agents_dir, adam_dir):
        """update_config で model が空の場合 ValueError が送出される"""
        manager = ConfigManager(agents_dir)
        with pytest.raises(ValueError):
            manager.update_config("adam", name="アダム", model="", description="テスト")

    def test_agent_not_found(self, agents_dir):
        """update_config で存在しないエージェントに対して AgentNotFoundError が送出される"""
        manager = ConfigManager(agents_dir)
        with pytest.raises(AgentNotFoundError):
            manager.update_config("nonexistent", name="テスト", model="test-model", description="")

    def test_preserves_unknown_fields(self, agents_dir, adam_dir):
        """update_config で config.yaml の未知のフィールドが保持される（将来の trigger 等を消さない）"""
        # 未知フィールドを追加
        raw = yaml.safe_load((adam_dir / "config.yaml").read_text(encoding="utf-8"))
        raw["trigger"] = {"cron": "*/10 * * * *", "enabled": True}
        (adam_dir / "config.yaml").write_text(yaml.dump(raw, allow_unicode=True), encoding="utf-8")

        manager = ConfigManager(agents_dir)
        manager.update_config("adam", name="アダム", model="claude-sonnet-4-20250514", description="更新")

        raw_after = yaml.safe_load((adam_dir / "config.yaml").read_text(encoding="utf-8"))
        assert raw_after["trigger"] == {"cron": "*/10 * * * *", "enabled": True}


# ============================================================
# ConfigManager — update_system_prompt
# ============================================================


class TestUpdateSystemPrompt:
    """CLAUDE.md の更新テスト"""

    def test_update_content(self, agents_dir, adam_dir):
        """update_system_prompt で CLAUDE.md の内容が更新される"""
        manager = ConfigManager(agents_dir)
        manager.update_system_prompt("adam", "新しいシステムプロンプト")

        content = (adam_dir / "CLAUDE.md").read_text(encoding="utf-8")
        assert content == "新しいシステムプロンプト"

    def test_empty_content(self, agents_dir, adam_dir):
        """update_system_prompt で空文字列を渡すと CLAUDE.md が空になる"""
        manager = ConfigManager(agents_dir)
        manager.update_system_prompt("adam", "")

        content = (adam_dir / "CLAUDE.md").read_text(encoding="utf-8")
        assert content == ""

    def test_agent_not_found(self, agents_dir):
        """update_system_prompt で存在しないエージェントに対して AgentNotFoundError が送出される"""
        manager = ConfigManager(agents_dir)
        with pytest.raises(AgentNotFoundError):
            manager.update_system_prompt("nonexistent", "テスト")

    def test_creates_claude_md_if_missing(self, agents_dir, eden_dir):
        """update_system_prompt で CLAUDE.md が存在しない場合、新規作成される"""
        assert not (eden_dir / "CLAUDE.md").exists()

        manager = ConfigManager(agents_dir)
        manager.update_system_prompt("eden", "エデンのプロンプト")

        assert (eden_dir / "CLAUDE.md").exists()
        content = (eden_dir / "CLAUDE.md").read_text(encoding="utf-8")
        assert content == "エデンのプロンプト"


# ============================================================
# REST API
# ============================================================


class TestSettingsAPI:
    """設定管理 REST API のテスト"""

    @pytest.fixture
    def client(self, agents_dir, adam_dir, eden_dir):
        from httpx import ASGITransport, AsyncClient

        from server.app import create_app

        app = create_app(agents_dir=agents_dir)
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test")

    async def test_put_config_success(self, client):
        """PUT /api/agents/{agent_id}/config が 200 と更新後の config を返す"""
        resp = await client.put("/api/agents/adam/config", json={
            "name": "新アダム",
            "model": "claude-haiku-4-5-20251001",
            "description": "新しい説明",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == "adam"
        assert data["config"]["name"] == "新アダム"
        assert data["config"]["model"] == "claude-haiku-4-5-20251001"
        assert data["config"]["description"] == "新しい説明"

    async def test_put_config_empty_name(self, client):
        """PUT /api/agents/{agent_id}/config で name が空の場合 400 を返す"""
        resp = await client.put("/api/agents/adam/config", json={
            "name": "",
            "model": "claude-sonnet-4-20250514",
            "description": "テスト",
        })

        assert resp.status_code == 400

    async def test_put_config_empty_model(self, client):
        """PUT /api/agents/{agent_id}/config で model が空の場合 400 を返す"""
        resp = await client.put("/api/agents/adam/config", json={
            "name": "アダム",
            "model": "",
            "description": "テスト",
        })

        assert resp.status_code == 400

    async def test_put_config_not_found(self, client):
        """PUT /api/agents/{agent_id}/config で存在しない agent_id に対して 404 を返す"""
        resp = await client.put("/api/agents/nonexistent/config", json={
            "name": "テスト",
            "model": "test-model",
            "description": "",
        })

        assert resp.status_code == 404

    async def test_put_system_prompt_success(self, client):
        """PUT /api/agents/{agent_id}/system-prompt が 200 と更新後の内容を返す"""
        resp = await client.put("/api/agents/adam/system-prompt", json={
            "content": "新しいプロンプト",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == "adam"
        assert data["content"] == "新しいプロンプト"

    async def test_put_system_prompt_not_found(self, client):
        """PUT /api/agents/{agent_id}/system-prompt で存在しない agent_id に対して 404 を返す"""
        resp = await client.put("/api/agents/nonexistent/system-prompt", json={
            "content": "テスト",
        })

        assert resp.status_code == 404

    async def test_config_persists_after_save(self, client):
        """保存後に GET /api/agents/{agent_id} で更新された値が取得できる"""
        await client.put("/api/agents/adam/config", json={
            "name": "更新アダム",
            "model": "claude-haiku-4-5-20251001",
            "description": "更新説明",
        })
        await client.put("/api/agents/adam/system-prompt", json={
            "content": "更新プロンプト",
        })

        resp = await client.get("/api/agents/adam")
        assert resp.status_code == 200
        data = resp.json()
        assert data["config"]["name"] == "更新アダム"
        assert data["config"]["model"] == "claude-haiku-4-5-20251001"
        assert data["config"]["description"] == "更新説明"
        assert data["system_prompt"] == "更新プロンプト"
