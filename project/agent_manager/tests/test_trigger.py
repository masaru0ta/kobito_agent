"""triggerコンポーネントのテスト（spec_trigger.md準拠）"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch
from pathlib import Path

import pytest
import yaml
from croniter import croniter

from server.config import ConfigManager
from server.runner import Runner, ThinkResult
from server.trigger import TriggerManager, TriggerStatus


# ============================================================
# config読み込み関連
# ============================================================


class TestTriggerConfig:
    """config.yamlのtriggerセクション読み込みテスト"""

    def test_trigger_section_exists(self, agents_dir):
        """config.yamlにtriggerセクションがある場合、正しく読み込める"""
        # Given: triggerセクションありのconfig.yaml
        d = agents_dir / "test_agent"
        d.mkdir()
        config = {
            "name": "テスト",
            "model": "claude-sonnet-4",
            "description": "テストエージェント",
            "trigger": {
                "cron": "*/10 * * * *",
                "enabled": True
            }
        }
        (d / "config.yaml").write_text(yaml.dump(config, allow_unicode=True), encoding="utf-8")

        # When: ConfigManagerで読み込み
        manager = ConfigManager(agents_dir)
        agent = manager.get_agent("test_agent")

        # Then: triggerセクションが正しく読み込まれる
        assert agent.config.trigger is not None
        assert agent.config.trigger.cron == "*/10 * * * *"
        assert agent.config.trigger.enabled == True

    def test_trigger_section_missing(self, agents_dir):
        """triggerセクションが省略された場合、トリガーなしとして扱う"""
        # Given: triggerセクションなしのconfig.yaml
        d = agents_dir / "test_agent"
        d.mkdir()
        config = {
            "name": "テスト",
            "model": "claude-sonnet-4",
            "description": "テストエージェント"
        }
        (d / "config.yaml").write_text(yaml.dump(config, allow_unicode=True), encoding="utf-8")

        # When: ConfigManagerで読み込み
        manager = ConfigManager(agents_dir)
        agent = manager.get_agent("test_agent")

        # Then: triggerセクションがNone
        assert agent.config.trigger is None

    def test_enabled_default_true(self, agents_dir):
        """enabledのデフォルトがtrueである"""
        # Given: enabledが省略されたtriggerセクション
        d = agents_dir / "test_agent"
        d.mkdir()
        config = {
            "name": "テスト",
            "model": "claude-sonnet-4",
            "description": "テストエージェント",
            "trigger": {
                "cron": "*/10 * * * *"
                # enabled省略
            }
        }
        (d / "config.yaml").write_text(yaml.dump(config, allow_unicode=True), encoding="utf-8")

        # When: ConfigManagerで読み込み
        manager = ConfigManager(agents_dir)
        agent = manager.get_agent("test_agent")

        # Then: enabledがTrueになる
        assert agent.config.trigger.enabled == True


# ============================================================
# cron式の解析と計算
# ============================================================


class TestCronParsing:
    """cron式の解析と次回実行時刻計算テスト"""

    def test_cron_parsing_valid(self):
        """cron式が正しく解析され、次回実行時刻が計算される"""
        # Given: 有効なcron式
        cron_expr = "*/10 * * * *"  # 10分ごと
        base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # When: croniterで解析
        cron = croniter(cron_expr, base_time)
        next_time = cron.get_next(datetime)

        # Then: 次回実行時刻が正しく計算される
        expected = datetime(2024, 1, 1, 12, 10, 0, tzinfo=timezone.utc)
        assert next_time == expected

    def test_cron_parsing_invalid(self):
        """不正なcron式でエラーが発生する"""
        # Given: 不正なcron式
        invalid_cron = "invalid cron expression"
        base_time = datetime.now(timezone.utc)

        # When/Then: croniterでエラーが発生
        with pytest.raises(Exception):
            croniter(invalid_cron, base_time)


# ============================================================
# 共通フィクスチャ
# ============================================================


@pytest.fixture
def trigger_config_agents_dir(tmp_path):
    """trigger設定ありのagents_dirフィクスチャ"""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    # triggerありエージェント
    adam_dir = agents_dir / "adam"
    adam_dir.mkdir()
    config_with_trigger = {
        "name": "アダム",
        "model": "claude-sonnet-4",
        "description": "システム設計者",
        "trigger": {
            "cron": "*/1 * * * *",  # 1分ごと（テスト用）
            "enabled": True
        }
    }
    (adam_dir / "config.yaml").write_text(yaml.dump(config_with_trigger, allow_unicode=True), encoding="utf-8")
    (adam_dir / "chat_history").mkdir()

    # triggerなしエージェント
    eden_dir = agents_dir / "eden"
    eden_dir.mkdir()
    config_without_trigger = {
        "name": "エデン",
        "model": "claude-haiku-4",
        "description": "情報収集"
    }
    (eden_dir / "config.yaml").write_text(yaml.dump(config_without_trigger, allow_unicode=True), encoding="utf-8")
    (eden_dir / "chat_history").mkdir()

    return agents_dir


@pytest.fixture
def mock_runner():
    """Runner のモック"""
    runner = Mock(spec=Runner)
    runner.think = AsyncMock()
    return runner


# ============================================================
# TriggerManagerクラス
# ============================================================


class TestTriggerManager:
    """TriggerManagerクラスの基本機能テスト"""

    @pytest.fixture
    def mock_runner(self):
        """Runner のモック"""
        runner = Mock(spec=Runner)
        runner.think = AsyncMock()
        return runner

    @pytest.fixture
    def trigger_config_agents_dir(self, tmp_path):
        """trigger設定ありのagents_dirフィクスチャ"""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        # triggerありエージェント
        adam_dir = agents_dir / "adam"
        adam_dir.mkdir()
        config_with_trigger = {
            "name": "アダム",
            "model": "claude-sonnet-4",
            "description": "システム設計者",
            "trigger": {
                "cron": "*/1 * * * *",  # 1分ごと（テスト用）
                "enabled": True
            }
        }
        (adam_dir / "config.yaml").write_text(yaml.dump(config_with_trigger, allow_unicode=True), encoding="utf-8")
        (adam_dir / "chat_history").mkdir()

        # triggerなしエージェント
        eden_dir = agents_dir / "eden"
        eden_dir.mkdir()
        config_without_trigger = {
            "name": "エデン",
            "model": "claude-haiku-4",
            "description": "情報収集"
        }
        (eden_dir / "config.yaml").write_text(yaml.dump(config_without_trigger, allow_unicode=True), encoding="utf-8")
        (eden_dir / "chat_history").mkdir()

        return agents_dir

    def test_trigger_manager_init(self, trigger_config_agents_dir, mock_runner):
        """TriggerManager.start()で全エージェントのスケジューラが起動する"""
        # Given: TriggerManager
        config_manager = ConfigManager(trigger_config_agents_dir)
        trigger_manager = TriggerManager(config_manager, mock_runner, trigger_config_agents_dir)

        # When: 初期化確認
        # Then: エラーなく初期化される
        assert trigger_manager is not None

    @pytest.mark.asyncio
    async def test_trigger_manager_start(self, trigger_config_agents_dir, mock_runner):
        """TriggerManager.start()で全エージェントのスケジューラが起動する"""
        # Given: TriggerManager
        config_manager = ConfigManager(trigger_config_agents_dir)
        trigger_manager = TriggerManager(config_manager, mock_runner, trigger_config_agents_dir)

        # When: スケジューラを開始
        await trigger_manager.start()

        # Then: エラーなく開始される
        # 実際のスケジューラ開始確認は実装時にテスト
        assert True  # 実装後にアサーションを追加

    @pytest.mark.asyncio
    async def test_trigger_manager_stop(self, trigger_config_agents_dir, mock_runner):
        """TriggerManager.stop()で全スケジューラが停止する"""
        # Given: 開始済みのTriggerManager
        config_manager = ConfigManager(trigger_config_agents_dir)
        trigger_manager = TriggerManager(config_manager, mock_runner, trigger_config_agents_dir)
        await trigger_manager.start()

        # When: スケジューラを停止
        await trigger_manager.stop()

        # Then: エラーなく停止される
        # 実際のスケジューラ停止確認は実装時にテスト
        assert True  # 実装後にアサーションを追加

    @pytest.mark.asyncio
    async def test_trigger_agent_execution(self, trigger_config_agents_dir, mock_runner):
        """trigger_agent()で指定エージェントの自律思考が1回実行される"""
        # Given: TriggerManager
        config_manager = ConfigManager(trigger_config_agents_dir)
        trigger_manager = TriggerManager(config_manager, mock_runner, trigger_config_agents_dir)

        # Mock設定
        mock_result = ThinkResult(
            agent_id="adam",
            response="test response",
            log_path=None,
            success=True,
            error=None
        )
        mock_runner.think.return_value = mock_result

        # When: エージェントをトリガー実行
        result = await trigger_manager.trigger_agent("adam")

        # Then: Runnerのthinkが呼ばれ、結果が返される
        mock_runner.think.assert_called_once_with("adam")
        assert result == mock_result

    def test_get_status(self, trigger_config_agents_dir, mock_runner):
        """get_status()で全エージェントのトリガー状態が返される"""
        # Given: TriggerManager
        config_manager = ConfigManager(trigger_config_agents_dir)
        trigger_manager = TriggerManager(config_manager, mock_runner, trigger_config_agents_dir)

        # When: ステータスを取得
        statuses = trigger_manager.get_status()

        # Then: triggerありのエージェントのみ含まれる
        assert len(statuses) == 1
        status = statuses[0]
        assert status.agent_id == "adam"
        assert status.enabled == True
        assert status.cron == "*/1 * * * *"


# ============================================================
# 排他制御とスキップ
# ============================================================


class TestTriggerExecution:
    """トリガー実行の排他制御テスト"""

    @pytest.mark.asyncio
    async def test_exclusive_execution(self, trigger_config_agents_dir):
        """同じエージェントの思考が同時に走らない（排他制御）"""
        # Given: 長時間実行されるmock runner
        slow_runner = Mock(spec=Runner)
        execution_started = asyncio.Event()

        async def slow_think(agent_id):
            execution_started.set()
            await asyncio.sleep(0.5)  # 500ms の長時間実行
            return ThinkResult(
                agent_id=agent_id,
                response="slow result",
                log_path=None,
                success=True,
                error=None
            )

        slow_runner.think = AsyncMock(side_effect=slow_think)

        config_manager = ConfigManager(trigger_config_agents_dir)
        trigger_manager = TriggerManager(config_manager, slow_runner, trigger_config_agents_dir)

        # When: 同じエージェントを同時にトリガー実行
        async def first_execution():
            return await trigger_manager.trigger_agent("adam")

        async def second_execution():
            await execution_started.wait()  # 最初の実行が開始されるまで待つ
            return await trigger_manager.trigger_agent("adam")

        task1 = asyncio.create_task(first_execution())
        task2 = asyncio.create_task(second_execution())

        results = await asyncio.gather(task1, task2)

        # Then: 1回目は成功、2回目はスキップされる
        # 実装時に具体的なアサーションを追加
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_skip_logging(self, trigger_config_agents_dir):
        """前回実行中の場合、トリガーがスキップされログに記録される"""
        # 実装時にログ記録のテストを追加
        # モックを使ってログ出力を確認
        pass


# ============================================================
# Web API
# ============================================================


class TestTriggerWebAPI:
    """トリガー関連のWeb APIテスト"""

    @pytest.fixture
    def app_with_trigger(self, trigger_config_agents_dir, mock_runner):
        """TriggerManager統合済みのFastAPIアプリ"""
        from server.app import create_app

        # Mock設定: デフォルトの戻り値を設定
        mock_result = ThinkResult(
            agent_id="adam",
            response="test response",
            log_path=None,
            success=True,
            error=None
        )
        mock_runner.think.return_value = mock_result

        config_manager = ConfigManager(trigger_config_agents_dir)
        trigger_manager = TriggerManager(config_manager, mock_runner, trigger_config_agents_dir)
        return create_app(config_manager=config_manager, trigger_manager=trigger_manager)

    @pytest.mark.asyncio
    async def test_get_triggers_api(self, app_with_trigger):
        """GET /api/triggers で全エージェントのトリガー状態が返される"""
        from httpx import ASGITransport, AsyncClient

        # Given: TriggerManager統合済みアプリ
        transport = ASGITransport(app=app_with_trigger)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # When: GET /api/triggers
            response = await client.get("/api/triggers")

        # Then: ステータス200で、trigger設定ありエージェントが返される
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["agent_id"] == "adam"
        assert data[0]["enabled"] == True
        assert data[0]["cron"] == "*/1 * * * *"
        assert "last_run" in data[0]
        assert "next_run" in data[0]
        assert "running" in data[0]

    @pytest.mark.asyncio
    async def test_post_trigger_manual(self, app_with_trigger):
        """POST /api/agents/{agent_id}/trigger で手動トリガーが動作する"""
        from httpx import ASGITransport, AsyncClient

        # Given: TriggerManager統合済みアプリ
        transport = ASGITransport(app=app_with_trigger)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # When: POST /api/agents/adam/trigger
            response = await client.post("/api/agents/adam/trigger")

        # Then: ステータス200で実行される
        assert response.status_code == 200
        # 実装時に詳細な結果確認を追加

    @pytest.mark.asyncio
    async def test_put_trigger_toggle(self, app_with_trigger):
        """PUT /api/agents/{agent_id}/trigger でトリガーの有効/無効を切り替える"""
        from httpx import ASGITransport, AsyncClient

        # Given: TriggerManager統合済みアプリ
        transport = ASGITransport(app=app_with_trigger)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # When: PUT /api/agents/adam/trigger で無効化
            response = await client.put("/api/agents/adam/trigger", json={"enabled": False})

        # Then: ステータス200で設定変更される
        assert response.status_code == 200
        # 実装時に状態確認を追加

    @pytest.mark.asyncio
    async def test_trigger_api_nonexistent_agent(self, app_with_trigger):
        """存在しないエージェントのトリガー操作で404が返される"""
        from httpx import ASGITransport, AsyncClient

        # Given: TriggerManager統合済みアプリ
        transport = ASGITransport(app=app_with_trigger)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # When: 存在しないエージェントにPOST
            response = await client.post("/api/agents/nonexistent/trigger")

        # Then: 404エラー
        assert response.status_code == 404


# ============================================================
# サーバーライフサイクル統合
# ============================================================


class TestServerIntegration:
    """サーバー起動/停止時のライフサイクル統合テスト"""

    @pytest.mark.asyncio
    async def test_server_startup_trigger_start(self, trigger_config_agents_dir):
        """サーバー起動時にトリガーが自動的に開始される"""
        # 実装時にサーバーstartupイベントのテストを追加
        pass

    @pytest.mark.asyncio
    async def test_server_shutdown_trigger_stop(self, trigger_config_agents_dir):
        """サーバー停止時にトリガーが正常に停止する（graceful shutdown）"""
        # 実装時にサーバーshutdownイベントのテストを追加
        pass

    def test_trigger_without_config_not_included(self, trigger_config_agents_dir, mock_runner):
        """triggerなしのエージェントはGET /api/triggersに含まれない"""
        # Given: triggerありとtriggerなしのエージェント
        config_manager = ConfigManager(trigger_config_agents_dir)
        trigger_manager = TriggerManager(config_manager, mock_runner, trigger_config_agents_dir)

        # When: ステータス取得
        statuses = trigger_manager.get_status()

        # Then: triggerありエージェントのみ含まれる（edenは含まれない）
        agent_ids = [s.agent_id for s in statuses]
        assert "adam" in agent_ids
        assert "eden" not in agent_ids