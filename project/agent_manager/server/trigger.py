"""triggerコンポーネント - 定期トリガーによる自律思考サイクル"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel
from croniter import croniter

from .config import ConfigManager
from .runner import Runner, ThinkResult


class TriggerStatus(BaseModel):
    """エージェントのトリガー状態"""
    agent_id: str
    enabled: bool
    cron: str
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    running: bool = False


class TriggerManager:
    """定期トリガー管理クラス"""

    def __init__(self, config_manager: ConfigManager, runner: Runner, agents_dir: Path):
        self.config_manager = config_manager
        self.runner = runner
        self.agents_dir = agents_dir
        self._running_agents: Dict[str, bool] = {}
        self._schedulers: Dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        """全エージェントのトリガーを開始する"""
        for agent in self.config_manager.list_agents():
            if agent.config.trigger is not None and agent.config.trigger.enabled:
                task = asyncio.create_task(self._schedule_agent(agent.agent_id, agent.config.trigger.cron))
                self._schedulers[agent.agent_id] = task

    async def stop(self) -> None:
        """全トリガーを停止する"""
        # スケジューラーのタスクをキャンセル
        for task in self._schedulers.values():
            task.cancel()
        self._schedulers.clear()

    async def trigger_agent(self, agent_id: str) -> ThinkResult:
        """指定エージェントの自律思考を1回実行する"""
        # 排他制御チェック
        if self._running_agents.get(agent_id, False):
            # 既に実行中の場合はスキップ（実装時にログ出力追加）
            return ThinkResult(
                agent_id=agent_id,
                response="skipped - already running",
                log_path=None,
                success=False,
                error=None
            )

        try:
            # 実行中フラグを設定
            self._running_agents[agent_id] = True

            # Runner.think()を呼び出し
            result = await self.runner.think(agent_id)
            return result

        finally:
            # 実行完了フラグをクリア
            self._running_agents[agent_id] = False

    def get_status(self) -> List[TriggerStatus]:
        """全エージェントのトリガー状態を返す"""
        statuses = []

        for agent in self.config_manager.list_agents():
            # triggerセクションがあるエージェントのみ対象
            if agent.config.trigger is not None:
                # 次回実行時刻を計算
                now = datetime.now(timezone.utc)
                try:
                    cron = croniter(agent.config.trigger.cron, now)
                    next_run = cron.get_next(datetime)
                except Exception:
                    next_run = None

                status = TriggerStatus(
                    agent_id=agent.agent_id,
                    enabled=agent.config.trigger.enabled,
                    cron=agent.config.trigger.cron,
                    next_run=next_run,
                    running=self._running_agents.get(agent.agent_id, False)
                )
                statuses.append(status)

        return statuses

    async def _schedule_agent(self, agent_id: str, cron_expr: str) -> None:
        """エージェントの定期実行スケジューラー"""
        while True:
            try:
                # 次回実行時刻を計算
                now = datetime.now(timezone.utc)
                cron = croniter(cron_expr, now)
                next_run = cron.get_next(datetime)

                # 次回実行まで待機
                wait_seconds = (next_run - now).total_seconds()
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)

                # トリガー実行
                await self.trigger_agent(agent_id)

            except asyncio.CancelledError:
                # タスクがキャンセルされた場合は正常終了
                break
            except Exception as e:
                # cron式エラーなど、回復不能なエラーの場合はスケジューラーを停止
                # 実際の運用では詳細なログ出力を行う
                break