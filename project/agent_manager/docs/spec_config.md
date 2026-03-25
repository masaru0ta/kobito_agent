# 仕様書: 1-1 config

## 1. 概要

エージェントの定義情報を読み込み、アプリケーション全体に提供するコンポーネント。
`agents/{name}/config.yaml` と `agents/{name}/CLAUDE.md` を読み込み、バリデーションを行い、他コンポーネント（runner, chat, web）が利用できる形で返す。

**この仕様の範囲**: config.yamlの読み込み・バリデーション・エージェント一覧取得・個別エージェント情報取得
**範囲外**: config.yamlの編集API（Phase 1ではWeb UIでの閲覧のみ）、トリガー設定の解釈（Phase 3以降）

**使用技術**: Python, PyYAML, Pydantic

## 2. 補足資料

### 2.1 参照ドキュメント
- `CLAUDE.md` のディレクトリ構成・エージェントの節

## 3. 機能詳細

### 3.1 ディレクトリ構造

```
agents/
  adam/
    CLAUDE.md          # システムプロンプト
    config.yaml        # エージェント定義
    mission.md         # 目的・方針（任意）
    task.md            # 現在のタスク（任意）
    think_prompt.md    # 自律思考プロンプト（任意、Web UIから編集可）
    .think_session_id  # 最後の思考セッションID（自動生成）
    chat_history/      # 会話履歴（chatコンポーネントが管理）
    output/            # 成果物
    memory/            # 記憶（Phase 5以降）
    log/               # 思考ログ
```

### 3.2 config.yaml スキーマ

```yaml
# 必須フィールド
name: "アダム"              # 表示名
model: "claude-sonnet-4-20250514"  # litellmが解釈できるモデルID

# 任意フィールド
description: "システムの設計者であり管理者"  # 一行説明（デフォルト: ""）
```

#### トリガー設定（Phase 4で追加）

```yaml
trigger:
  cron: "*/10 * * * *"    # cron式（5フィールド形式）
  enabled: true            # 有効/無効
```

`trigger` フィールドがない場合、トリガーは無効として扱う。

### 3.3 Pydanticモデル

```python
class TriggerConfig(BaseModel):
    cron: str                          # cron式（5フィールド形式）
    enabled: bool = True               # 有効/無効

class AgentConfig(BaseModel):
    name: str                          # 表示名
    model: str                         # モデルID
    description: str = ""              # 一行説明

class AgentInfo(BaseModel):
    agent_id: str                      # ディレクトリ名（= 識別子）
    config: AgentConfig                # config.yaml の内容
    system_prompt: str                 # CLAUDE.md の内容
    mission: str | None                # mission.md の内容（なければNone）
    task: str | None                   # task.md の内容（なければNone）
    think_prompt: str | None           # think_prompt.md の内容（なければNone → デフォルト使用）
```

### 3.4 処理ロジック

#### エージェント探索
1. `agents/` ディレクトリ直下のサブディレクトリを列挙する
2. 各サブディレクトリに `config.yaml` が存在するかチェックする
3. `config.yaml` が存在するディレクトリのみエージェントとして認識する

#### config読み込み
1. `config.yaml` をYAMLとしてパースする
2. Pydanticモデル `AgentConfig` でバリデーションする
3. バリデーションエラーがあれば例外を送出する（フォールバックしない）
4. `CLAUDE.md` を読み込む（存在しなければ空文字列）
5. `mission.md` を読み込む（存在しなければNone）
6. `task.md` を読み込む（存在しなければNone）
7. `think_prompt.md` を読み込む（存在しなければNone → runner側でデフォルト使用）
8. `AgentInfo` を返す

#### エラーハンドリング
- `agents/` ディレクトリが存在しない → 空リストを返す
- `config.yaml` のYAMLパースエラー → 例外送出（該当エージェントをスキップしない）
- `config.yaml` のバリデーションエラー → 例外送出（該当エージェントをスキップしない）
- `CLAUDE.md` が存在しない → system_promptを空文字列にする

### 3.5 公開インターフェース

```python
class ConfigManager:
    def __init__(self, agents_dir: Path):
        """agents_dirはagents/ディレクトリのパス"""

    def list_agents(self) -> list[AgentInfo]:
        """全エージェントの情報を返す。毎回ファイルを読み直す"""

    def get_agent(self, agent_id: str) -> AgentInfo:
        """指定エージェントの情報を返す。存在しなければAgentNotFoundErrorを送出"""
```

### 3.6 REST API

| メソッド | パス | 説明 | レスポンス |
|---------|------|------|-----------|
| GET | `/api/agents` | エージェント一覧 | `AgentInfo[]` のJSON |
| GET | `/api/agents/{agent_id}` | エージェント詳細 | `AgentInfo` のJSON |

#### GET /api/agents レスポンス例
```json
[
  {
    "agent_id": "adam",
    "config": {
      "name": "アダム",
      "model": "claude-sonnet-4-20250514",
      "description": "システムの設計者であり管理者"
    },
    "system_prompt": "あなたは...",
    "mission": "このシステムを設計し...",
    "task": null
  }
]
```

#### エラーレスポンス
- `GET /api/agents/{agent_id}` で存在しないagent_id → 404

## 4. 非機能要件

- エージェント一覧取得は毎回ファイルを読み直す（ホットリロード前提で、キャッシュしない）
- エージェント数は数十体を想定。パフォーマンス最適化は不要

## 5. 考慮事項・制限事項

- config.yamlの書き込み・編集APIはPhase 1では提供しない
- トリガー設定（triggers フィールド）はPhase 3で拡張する
- モデルIDのバリデーション（実在するモデルかどうか）は行わない。litellmが実行時にエラーを出す

## 6. テスト方針

- ユニットテスト（pytest）でConfigManagerの全メソッドをテストする
- テスト用のagentsディレクトリをtmpディレクトリに作成してテストする
- 正常系: 有効なconfig.yamlの読み込み、複数エージェントの一覧取得
- 異常系: ディレクトリなし、config.yaml不正、必須フィールド欠落、agent_id不一致
- APIテスト（httpx + FastAPI TestClient）でエンドポイントをテストする

## 7. テスト項目

### config読み込み
- 有効なconfig.yamlを読み込み、AgentConfigが正しく生成される
- CLAUDE.mdが存在する場合、system_promptに内容が設定される
- CLAUDE.mdが存在しない場合、system_promptが空文字列になる
- mission.mdが存在する場合、missionに内容が設定される
- mission.mdが存在しない場合、missionがNoneになる
- task.mdが存在する場合、taskに内容が設定される
- task.mdが存在しない場合、taskがNoneになる
- think_prompt.mdが存在する場合、think_promptに内容が設定される
- think_prompt.mdが存在しない場合、think_promptがNoneになる

### トリガー設定
- config.yamlにtriggerフィールドがある場合、TriggerConfigとして読み込める
- triggerフィールドがない場合、トリガーは無効として扱われる
- update_configでtriggerフィールドが保持される（未知フィールドを消さない）

### エージェント一覧
- agents/ディレクトリに複数エージェントがある場合、全エージェントが返る
- agents/ディレクトリが空の場合、空リストが返る
- agents/ディレクトリが存在しない場合、空リストが返る
- config.yamlがないサブディレクトリは無視される

### エラーハンドリング
- config.yamlのYAMLが不正な場合、例外が送出される
- config.yamlのnameフィールドが欠落している場合、バリデーションエラーになる
- config.yamlのmodelフィールドが欠落している場合、バリデーションエラーになる
- 存在しないagent_idでget_agentを呼ぶとAgentNotFoundErrorが送出される

### REST API
- GET /api/agents が200とエージェント一覧を返す
- GET /api/agents/{agent_id} が200とエージェント詳細を返す
- GET /api/agents/{agent_id} で存在しないIDを指定すると404を返す
