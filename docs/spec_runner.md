# 仕様書: 1-2 runner

## 1. 概要

1回のLLM呼び出しを組み立てて実行するエンジン。
エージェントの設定・システムプロンプト・会話履歴を受け取り、LLMにリクエストを送り、応答をストリーミングで返す。

Phase 1ではチャット応答に特化する。Phase 2で自律思考（mission/task読み込み→作業実行→成果物出力）に拡張する。

**この仕様の範囲**: プロンプト組み立て、LLM呼び出し（ストリーミング）、応答返却
**範囲外**: 自律思考サイクル（Phase 2）、記憶の想起・保存（Phase 5）、ツール使用

**使用技術**: Python, claude -p（Claude Code CLIのヘッドレスモード）

## 2. 補足資料

### 2.1 参照ドキュメント
- `CLAUDE.md` の動作フロー・チャットの節
- `docs/spec_config.md` — AgentInfo の定義

## 3. 機能詳細

### 3.1 プロンプト組み立て（Phase 1）

LLMに送るメッセージ配列を以下の順序で構築する:

```
[
  { role: "system", content: システムプロンプト },
  { role: "user",   content: ユーザーメッセージ1 },
  { role: "assistant", content: エージェント応答1 },
  ...（会話履歴）
  { role: "user",   content: 最新のユーザーメッセージ }
]
```

#### システムプロンプト
エージェントの `CLAUDE.md` の内容をそのまま使う。空の場合はsystemメッセージを省略する。

### 3.2 LLM呼び出し

`claude -p`（Claude Code CLIのヘッドレスモード）を `asyncio.create_subprocess_exec` で非同期実行する。

```python
cmd = [
    "claude", "-p",
    "--output-format", "stream-json",
    "--verbose",
    "--no-session-persistence",
    "--model", agent_info.config.model,
]
if agent_info.system_prompt:
    cmd.extend(["--system-prompt", agent_info.system_prompt])
cmd.append(prompt)

proc = await asyncio.create_subprocess_exec(
    *cmd,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
stdout_bytes, stderr_bytes = await proc.communicate()
```

- `--output-format stream-json` の出力から `type: "result"` の行を抽出して応答テキストを取得する
- claude -pは一括応答のため、疑似ストリーミング（チャンク分割してyield）で返す
- 非ストリーミング呼び出しも提供する

### 3.3 公開インターフェース

```python
class Runner:
    async def run(
        self,
        agent_info: AgentInfo,
        messages: list[Message],
    ) -> str:
        """非ストリーミング呼び出し。完全な応答テキストを返す"""

    async def run_stream(
        self,
        agent_info: AgentInfo,
        messages: list[Message],
    ) -> AsyncGenerator[str, None]:
        """ストリーミング呼び出し。テキストチャンクをyieldする"""
```

#### Message型

```python
class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str
```

### 3.4 エラーハンドリング

- LLM APIエラー（認証失敗、レート制限、モデル不正等）→ 例外をそのまま送出する
- フォールバック処理は行わない（別のモデルに切り替える等はしない）
- 空のメッセージリスト → ValueError を送出する

## 4. 非機能要件

- ストリーミングレスポンスの最初のチャンクが返るまでの遅延は、LLM APIの応答速度に依存する（runner側でバッファリングしない）

## 5. 考慮事項・制限事項

- Phase 1ではツール使用（function calling）は実装しない
- Phase 1ではトークン数の管理・会話の切り詰めは実装しない（会話が長くなるとAPIエラーになる可能性がある）
- Claude Code CLI（`claude`コマンド）がPATHに存在し、認証済みである前提

## 6. テスト方針

- ユニットテスト（pytest）でRunnerクラスをテストする
- LLM呼び出しはモックする（asyncio.create_subprocess_execをモック）
- プロンプト組み立てのロジックをテストする（メッセージ配列の構造）
- ストリーミングのテストはAsyncGeneratorのモックで行う

## 7. テスト項目

### プロンプト組み立て
- システムプロンプトがmessages配列の先頭にsystemロールで含まれる
- システムプロンプトが空の場合、systemメッセージが省略される
- 会話履歴がmessages配列に正しい順序で含まれる
- 最新のユーザーメッセージがmessages配列の末尾に含まれる

### LLM呼び出し（非ストリーミング）
- runメソッドがLLMの応答テキストを返す
- 指定されたモデルIDでclaude -pが呼ばれる

### LLM呼び出し（ストリーミング）
- run_streamメソッドがテキストチャンクをyieldする
- 全チャンクを結合すると完全な応答テキストになる

### エラーハンドリング
- 空のメッセージリストでValueErrorが送出される
- LLM APIエラーがそのまま送出される（キャッチして握りつぶさない）

---

# Phase 3: 自律思考サイクル

## 8. 概要

エージェントが自分で考え、1ステップだけ作業を進める機能。`Runner.think()` メソッドとして追加する。

10分に1回、定期トリガー（`spec_trigger.md` 参照）から呼び出される。1回の実行は2-3分で終わる短いタスクを1ステップだけ進める。

## 9. 処理フロー

```
1. mission.md を読む（なければ CLAUDE.md から生成）
2. task.md を読む（なければ mission.md から生成）
3. 自律思考プロンプトを組み立てる
4. claude -p を実行（タイムアウト: 180秒）
5. 結果を解析する
6. task.md を更新する（進捗を反映）
7. 成果物があれば output/ に保存し、index.md を更新する
8. 思考ログを log/ に保存する
```

### 9.1 mission.md の読み込み・生成

- `agents/{name}/mission.md` を読む
- ファイルが存在しない場合、LLMに生成させる:
  - CLAUDE.md の内容を渡し「このエージェントの目的・方針・継続的な責務を mission.md として書け」と指示
  - 生成結果を `agents/{name}/mission.md` に保存
- これは通常の `Runner.run()` を使って行う（自律思考の前段階）

### 9.2 task.md の読み込み・生成

- `agents/{name}/task.md` を読む
- ファイルが存在しない場合、LLMに生成させる:
  - mission.md の内容を渡し「このミッションから、今やるべき具体的な作業リストを task.md として書け」と指示
  - 生成結果を `agents/{name}/task.md` に保存

### 9.3 自律思考プロンプトの組み立て

以下の情報をLLMに渡す:

- **システムプロンプト**: CLAUDE.md（`--system-prompt` で渡す）
- **ユーザープロンプト**: 下記テンプレートを `stdin` で渡す

```
あなたの現在のミッション:
---
{mission.md の内容}
---

あなたの現在のタスクリスト:
---
{task.md の内容}
---

上記のタスクリストから、今やるべきことを1つ選んで実行してください。

ルール:
- 1回の実行で2-3分で終わる範囲に絞ること
- 大きなタスクは小さなステップに分解し、1ステップだけ進めること
- 完了したタスクにはチェックを入れ、新たに必要になったタスクは追加すること

実行結果を以下のJSON形式で返してください（JSON以外のテキストを含めないこと）:

{
  "action": "実行した内容の要約（1行）",
  "result": "実行結果の詳細",
  "task_update": "更新後のtask.md全文（進捗を反映）",
  "output": {
    "filename": "成果物のファイル名（.md）。なければnull",
    "content": "成果物の内容。なければnull"
  }
}
```

### 9.4 claude -p の実行

- 既存の `Runner._run_claude()` を使う
- タイムアウト: 180秒（3分）
- cwdはエージェントのディレクトリ (`agents/{name}/`)
- session_id は使わない（毎回新規セッション）

### 9.5 結果の解析

- LLMの応答からJSONを抽出する
  - 応答全体がJSONの場合: そのままパース
  - markdownコードブロック内にJSONがある場合: コードブロック内を抽出してパース
- JSONのパースに失敗した場合: エラーとする。フォールバック処理はしない

### 9.6 task.md の更新

- `task_update` フィールドの内容で `agents/{name}/task.md` を上書きする
- `task_update` が空・null・存在しない場合は更新しない

### 9.7 成果物の保存

- `output.filename` と `output.content` が両方存在する場合:
  - `agents/{name}/output/` ディレクトリを作成（なければ）
  - `agents/{name}/output/{filename}` に保存
  - `agents/{name}/output/index.md` を更新（なければ新規作成）
    - 形式: `- [{filename}](./{filename}) — {actionの要約}`
    - 既存エントリがあれば上書き、なければ追記
- 成果物がない場合はスキップ

### 9.8 思考ログの保存

- `agents/{name}/log/` ディレクトリに保存（なければ作成）
- ファイル名: `{YYYYMMDD_HHMMSS}.json`（UTCタイムスタンプ）
- 内容:

```json
{
  "timestamp": "ISO8601",
  "agent_id": "エージェントID",
  "action": "実行した内容の要約",
  "result": "実行結果の詳細",
  "prompt": "LLMに送ったプロンプト（デバッグ用）",
  "raw_response": "LLMの生の応答",
  "success": true,
  "error": null
}
```

エラー時:
```json
{
  "timestamp": "ISO8601",
  "agent_id": "エージェントID",
  "action": "",
  "result": "",
  "prompt": "LLMに送ったプロンプト",
  "raw_response": "LLMの生の応答",
  "success": false,
  "error": "エラーメッセージ"
}
```

## 10. 公開インターフェース（Phase 3追加分）

```python
@dataclass
class ThinkResult:
    """自律思考の結果"""
    agent_id: str
    action: str          # 実行した内容の要約
    result: str          # 実行結果の詳細
    task_updated: bool   # task.md を更新したか
    output_saved: bool   # 成果物を保存したか
    log_path: str        # ログファイルのパス
    success: bool        # 成功したか
    error: str | None    # エラーメッセージ（あれば）

class Runner:
    async def think(self, agent_info: AgentInfo) -> ThinkResult:
        """自律思考サイクルを1回実行する"""

    async def _ensure_mission(self, agent_info: AgentInfo) -> str:
        """mission.md を読む。なければ生成して保存する。内容を返す"""

    async def _ensure_task(self, agent_info: AgentInfo, mission: str) -> str:
        """task.md を読む。なければ生成して保存する。内容を返す"""

    def _build_think_prompt(self, mission: str, task: str) -> str:
        """自律思考用のプロンプトを組み立てる"""

    def _parse_think_response(self, raw: str) -> dict:
        """LLM応答からJSONを抽出してパースする"""

    def _save_output(self, agent_info: AgentInfo, filename: str, content: str, action: str) -> None:
        """成果物を保存し、index.md を更新する"""

    def _save_log(self, agent_id: str, log_data: dict) -> str:
        """思考ログを保存し、ファイルパスを返す"""
```

## 11. Web API（Phase 3追加分）

### POST /api/agents/{agent_id}/think

手動で自律思考を1回トリガーする（デバッグ・テスト用）。

**レスポンス** (200):
```json
{
  "agent_id": "adam",
  "action": "実行した内容の要約",
  "result": "実行結果の詳細",
  "task_updated": true,
  "output_saved": false,
  "log_path": "log/20260325_120000.json",
  "success": true,
  "error": null
}
```

**エラー** (404): エージェントが見つからない

### GET /api/agents/{agent_id}/logs

思考ログの一覧を返す（新しい順）。

**レスポンス** (200):
```json
[
  {
    "filename": "20260325_120000.json",
    "timestamp": "2026-03-25T12:00:00Z",
    "action": "実行した内容の要約",
    "success": true
  }
]
```

### GET /api/agents/{agent_id}/logs/{filename}

指定した思考ログの詳細を返す。

### GET /api/agents/{agent_id}/outputs

成果物ファイルの一覧を返す。

**レスポンス** (200):
```json
[
  {
    "filename": "report.md",
    "size": 1234
  }
]
```

### GET /api/agents/{agent_id}/outputs/{filename}

成果物の内容をテキストで返す。

## 12. テスト項目（Phase 3）

### mission.md / task.md の管理
- [ ] mission.md が存在する場合、正しく読み込める
- [ ] mission.md が存在しない場合、LLMで生成して保存する
- [ ] task.md が存在する場合、正しく読み込める
- [ ] task.md が存在しない場合、LLMで生成して保存する

### プロンプト組み立て
- [ ] 自律思考プロンプトに mission.md の内容が含まれる
- [ ] 自律思考プロンプトに task.md の内容が含まれる
- [ ] 自律思考プロンプトに実行ルールとJSON形式の指示が含まれる

### 応答の解析
- [ ] JSON応答を正しくパースできる
- [ ] markdownコードブロック内のJSONを抽出してパースできる
- [ ] JSONパース失敗時にエラーとなる（フォールバックしない）

### task.md の更新
- [ ] task_update がある場合、task.md が上書きされる
- [ ] task_update が空/nullの場合、task.md は変更されない

### 成果物の保存
- [ ] output.filename と output.content がある場合、output/ に保存される
- [ ] output/index.md が正しく更新される（新規作成・既存更新の両方）
- [ ] 成果物がない場合、output/ は変更されない

### 思考ログ
- [ ] ログが log/ に保存される
- [ ] ログファイル名が YYYYMMDD_HHMMSS.json 形式である
- [ ] 成功時のログに action, result, prompt, raw_response が含まれる
- [ ] エラー時のログに error が含まれ、success が false である

### think() の統合
- [ ] think() が正常に ThinkResult を返す
- [ ] think() でエラーが発生しても ThinkResult を返す（success=false）

### Web API
- [ ] POST /api/agents/{agent_id}/think が ThinkResult を返す
- [ ] GET /api/agents/{agent_id}/logs が新しい順でログ一覧を返す
- [ ] GET /api/agents/{agent_id}/logs/{filename} がログ詳細を返す
- [ ] GET /api/agents/{agent_id}/outputs が成果物一覧を返す
- [ ] GET /api/agents/{agent_id}/outputs/{filename} が成果物内容を返す
- [ ] 存在しないエージェントに対して404を返す
