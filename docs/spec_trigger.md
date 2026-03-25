# trigger コンポーネント仕様書

## 概要

triggerはエージェントの自律思考サイクルを定期的に発火させるエンジンである。

フェーズ3では cron 式の定期トリガーを実装する。フェーズ4でエージェント間トリガーを追加する。

## 定期トリガー（cron）

### config.yaml の拡張

```yaml
name: "アダム"
model: "claude-sonnet-4-20250514"
description: "システムの設計者であり管理者"
trigger:
  cron: "*/10 * * * *"   # 10分ごと
  enabled: true           # トリガーの有効/無効
```

- `trigger` セクションが省略された場合、トリガーなし（チャット専用エージェント）
- `enabled` のデフォルトは `true`
- cron式は標準的な5フィールド形式（分 時 日 月 曜日）

### TriggerManager

サーバー起動時にすべてのエージェントのトリガー設定を読み込み、スケジューラを起動する。

```python
class TriggerManager:
    def __init__(self, config_manager: ConfigManager, runner: Runner, agents_dir: Path):
        ...

    async def start(self) -> None:
        """全エージェントのトリガーを開始する"""

    async def stop(self) -> None:
        """全トリガーを停止する"""

    async def trigger_agent(self, agent_id: str) -> ThinkResult:
        """指定エージェントの自律思考を1回実行する"""

    def get_status(self) -> list[TriggerStatus]:
        """全エージェントのトリガー状態を返す"""
```

### 実行の排他制御

- 同じエージェントの自律思考が同時に複数走らないようにする
- 前回の思考がまだ実行中なら、今回のトリガーはスキップする
- スキップした場合、ログに記録する

### スケジューリング

- Python の `asyncio` ベースで実装する
- 外部ライブラリ: `croniter` を使ってcron式を解析し、次回実行時刻を計算する
- サーバー起動時に `TriggerManager.start()` を呼ぶ
- サーバー停止時に `TriggerManager.stop()` を呼ぶ（graceful shutdown）

### 処理フロー

```
1. スケジューラが発火
2. 排他ロックを取得（取得できなければスキップ）
3. Runner.think() を呼ぶ
4. 結果をログに記録
5. ロックを解放
6. 次回実行時刻を計算して待機
```

## Web API

### GET /api/triggers

全エージェントのトリガー状態を返す。

**レスポンス**:
```json
[
  {
    "agent_id": "adam",
    "enabled": true,
    "cron": "*/10 * * * *",
    "last_run": "ISO8601 or null",
    "next_run": "ISO8601 or null",
    "running": false
  }
]
```

### POST /api/agents/{agent_id}/trigger

手動でトリガーを1回発火する。

### PUT /api/agents/{agent_id}/trigger

トリガーの有効/無効を切り替える。

**リクエスト**:
```json
{
  "enabled": true
}
```

## テスト項目

- [ ] config.yaml に trigger セクションがある場合、正しく読み込める
- [ ] trigger セクションが省略された場合、トリガーなしとして扱う
- [ ] enabled のデフォルトが true である
- [ ] cron 式が正しく解析され、次回実行時刻が計算される
- [ ] 不正な cron 式でエラーが発生する
- [ ] TriggerManager.start() で全エージェントのスケジューラが起動する
- [ ] TriggerManager.stop() で全スケジューラが停止する
- [ ] トリガー発火時に Runner.think() が呼ばれる
- [ ] 同じエージェントの思考が同時に走らない（排他制御）
- [ ] 前回実行中の場合、トリガーがスキップされログに記録される
- [ ] 手動トリガー（POST /api/agents/{agent_id}/trigger）が正しく動作する
- [ ] トリガーの有効/無効切り替え（PUT）が正しく動作する
- [ ] GET /api/triggers が全エージェントの状態を返す
- [ ] トリガーなしのエージェントは GET /api/triggers に含まれない
- [ ] サーバー起動時にトリガーが自動的に開始される
- [ ] サーバー停止時にトリガーが正常に停止する（graceful shutdown）
