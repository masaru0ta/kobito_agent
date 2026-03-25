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

```python
    async def summarize_text(
        self,
        agent_info: AgentInfo,
        text: str,
    ) -> dict:
        """テキストを要約してtitle/summaryを返す。
        会話や思考ログなど、任意のテキストの要約に再利用できる。
        戻り値: {"title": "テーマと結論（30文字以内）", "summary": "要約（100文字以内）"}
        """
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

エージェントが自分で考え、1ステップだけ作業を進める機能。`Runner.think_stream()` メソッドで実装。

Claude Code（`claude -p`）にファイル操作を含む全作業を委ね、runner側はプロンプト送信・ストリーミング中継・ログ保存のみ行う。

## 9. 処理フロー

### 9.1 作業フェーズ

```
1. 思考プロンプトを決定する（think_prompt.md or デフォルト / 続行時は専用プロンプト）
2. プロンプトイベントをフロントに通知する
3. claude -p をストリーミング実行する（cwdはエージェントディレクトリ）
4. stdout の各JSON行をリアルタイムにパースし、SSEイベントとしてフロントに中継する
5. session_id を .think_session_id に保存する
```

### 9.2 報告フェーズ

作業完了後、同じセッションに報告用プロンプトを投げる:

```
今回の作業で何をしたか、以下の形式でまとめろ。ツールは使うな。

## 報告
- （やったことを完了形で）

## 変更ファイル
- （変更したファイル名）

## 次回
- （次にやるべきこと）
```

この2フェーズ分離により、作業中の中間テキスト（「〜します」）ではなく、完了形の報告が結果として保存される。

### 9.3 思考プロンプト

#### 新規思考

`agents/{name}/think_prompt.md` の内容を使う。ファイルがなければ `DEFAULT_THINK_PROMPT` を使う。

デフォルトプロンプト:
```
あなたは今から「自律思考」を1回実行する。

## 手順
1. 直近10件の会話履歴の要約を読むこと
2. 要約されていない会話履歴があれば要約を行う
3. mission.md を読む。なければ思考停止
4. task.md を読む。なければ mission.md から今やるべき具体的な作業リストを作成する
5. タスクリストから今やるべきことを1つ選んで実行する
6. タスクが進捗したら task.md を更新する
5. 成果物は output/ に .md ファイルとして保存する

## ルール
- 大きなタスクは小さなステップに分解し、1ステップだけ進めること
- タスクが進捗したら task.md を更新すること
```

- Web UIの「プロンプト」ボタンから編集可能
- `GET/PUT /api/agents/{agent_id}/think-prompt` で取得・更新

#### 続行思考

前回の `session_id` を使って `--resume` で実行する。プロンプトは短い:

```
前回の続きを1ステップだけ進めろ。
タスクが進捗したら task.md を更新すること。
```

前回のコンテキストがセッションに残っているため、mission/taskの読み直し指示は不要。

### 9.4 セッション管理

- 思考完了時に `session_id` を `agents/{name}/.think_session_id` に保存
- 続行思考時にこのファイルを読んで `--resume` に渡す
- 新規思考では新しいセッションが作られる

### 9.5 ストリーミング基盤

`_run_claude_stream()` — `subprocess.Popen` + スレッドでstdoutを行単位にリアルタイム読み取り。Windows互換。

- stdinにプロンプトを書き込んでclose
- 別スレッドでstdoutを行単位に読み、JSON行をasyncio.Queueに投入
- メインスレッドでQueueから読んでyield
- 非JSON行はエラー情報として蓄積（プロセス失敗時にエラーメッセージに含める）

チャットの `run_stream()` も同じ基盤を使う。テキストは30文字ずつチャンク分割して疑似ストリーミング。

### 9.6 思考ログの保存

- `agents/{name}/log/` ディレクトリに保存
- ファイル名: `{YYYYMMDD_HHMMSS}.json`（UTCタイムスタンプ）

```json
{
  "timestamp": "ISO8601",
  "agent_id": "エージェントID",
  "prompt": "LLMに送ったプロンプト",
  "response": "報告フェーズの応答テキスト",
  "events": [
    {"type": "tool_use", "content": "Read: mission.md"},
    {"type": "text", "content": "タスクを確認する"},
    {"type": "tool_use", "content": "Edit: task.md"}
  ],
  "session_id": "claude session id",
  "success": true,
  "error": null
}
```

`events` 配列にストリーミング中の全イベント（ツール使用、テキスト）を保存する。思考履歴からログを開いたとき、実行過程を再現表示できる。

## 10. 公開インターフェース（Phase 3）

```python
class Runner:
    async def think_stream(
        self, agent_info: AgentInfo, agent_dir: Path,
        session_id: str | None = None,
    ) -> AsyncGenerator[dict, None]:
        """自律思考をストリーミング実行。以下のイベントをyieldする:
        - {"type": "prompt", "content": "送信プロンプト"}
        - {"type": "text", "content": "テキストデルタ"}
        - {"type": "tool_use", "content": "Read: mission.md"}
        - {"type": "result", "content": "報告テキスト", "log_path": "...", "success": true}
        - {"type": "error", "content": "エラーメッセージ", "log_path": "...", "success": false}
        """

    async def think(self, agent_id: str) -> ThinkResult:
        """トリガー用の非ストリーミング呼び出し。think_streamを内部で実行する"""

    async def _run_claude_stream(
        self, agent_info: AgentInfo, prompt: str,
        session_id: str | None = None, no_sync: bool = False,
    ) -> AsyncGenerator[dict, None]:
        """claude -p をストリーミング実行。stdoutの各JSON行をyieldする"""

    def _save_log(self, agent_dir: Path, log_data: dict) -> str:
        """思考ログを保存し、ファイルパスを返す"""
```

## 11. Web API（Phase 3追加分）

### POST /api/agents/{agent_id}/think

自律思考を実行する。SSEストリーミングレスポンスを返す。

**クエリパラメータ**:
- `resume` (bool, optional): `true` で前回セッションを続行

**レスポンス**: SSE (text/event-stream)

```
event: prompt
data: 思考プロンプトの内容

event: tool_use
data: Read: mission.md

event: text
data: タスクを確認する

event: result
data: {"type":"result","content":"## 報告\n- ...","log_path":"...","success":true}
```

### GET /api/agents/{agent_id}/think-prompt

思考プロンプトを取得する。`think_prompt.md` がなければデフォルトプロンプトを返す。

### PUT /api/agents/{agent_id}/think-prompt

思考プロンプトを更新する（`think_prompt.md` に保存）。

### GET /api/agents/{agent_id}/logs

思考ログの一覧を返す（新しい順）。

### GET /api/agents/{agent_id}/logs/{filename}

思考ログの詳細を返す（events配列を含む）。

### GET /api/agents/{agent_id}/outputs

成果物ファイルの一覧を返す。

### GET /api/agents/{agent_id}/outputs/{filename}

成果物の内容をテキストで返す。

## 12. テスト項目（Phase 3）

### 思考プロンプト
- [ ] think_prompt.md が存在する場合、その内容がプロンプトとして使われる
- [ ] think_prompt.md が存在しない場合、デフォルトプロンプトが使われる
- [ ] Web UIからthink_prompt.mdを編集・保存できる

### ストリーミング
- [ ] think_stream がプロンプトイベントをyieldする
- [ ] think_stream がテキストイベントをyieldする
- [ ] think_stream がツール使用イベントをyieldする
- [ ] think_stream が結果イベント（報告テキスト）をyieldする
- [ ] エラー時にエラーイベントをyieldする

### セッション管理
- [ ] 新規思考で新しいセッションが作られる
- [ ] session_id が .think_session_id に保存される
- [ ] 続行思考で前回のsession_idが使われる（--resume）
- [ ] 続行時のプロンプトが短縮版になる

### 報告フェーズ
- [ ] 作業完了後に報告用プロンプトが同じセッションに送られる
- [ ] 報告テキストが結果として保存される

### 思考ログ
- [ ] ログが log/ に保存される
- [ ] ログにevents配列が含まれる
- [ ] ログにsession_idが含まれる
- [ ] エラー時のログに error が含まれ、success が false である

### Web API
- [ ] POST /api/agents/{agent_id}/think がSSEストリーミングを返す
- [ ] resume=true で前回セッションを続行できる
- [ ] GET /api/agents/{agent_id}/think-prompt がプロンプトを返す
- [ ] PUT /api/agents/{agent_id}/think-prompt がプロンプトを保存する
- [ ] GET /api/agents/{agent_id}/logs が新しい順でログ一覧を返す
- [ ] GET /api/agents/{agent_id}/logs/{filename} がログ詳細（events含む）を返す
- [ ] 存在しないエージェントに対して404を返す
