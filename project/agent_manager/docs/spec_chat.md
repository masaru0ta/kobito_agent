# 仕様書: 1-3 chat

## 1. 概要

ユーザーとエージェントのチャット処理を担当するコンポーネント。
メッセージの送受信、会話履歴の永続化、およびチャットAPIエンドポイントを提供する。

**この仕様の範囲**: ユーザー×エージェントの1対1チャット、会話履歴の保存・取得、ストリーミング応答、CLI（Claude Code）からの会話同期
**範囲外**: エージェント間チャット（Phase 4）、記憶の想起・保存（Phase 5）、複数人チャット

**使用技術**: Python, FastAPI (SSE), JSON

## 2. 補足資料

### 2.1 参照ドキュメント
- `CLAUDE.md` の動作フロー・チャットの節
- `docs/spec_config.md` — AgentInfo の定義
- `docs/spec_runner.md` — Runner の定義

## 3. 機能詳細

### 3.1 会話履歴の保存形式

会話履歴は以下の場所に保存する。

- エージェントとの会話: `agents/{agent_id}/chat_history/`
- エージェントなしの会話（プロジェクトルートでCLI起動時）: `chat_history/`

#### ファイル構造
```
kobito_agent/
  chat_history/                     # エージェントなしの会話
    {conversation_id}.json
  agents/adam/chat_history/         # エージェントとの会話
    {conversation_id}.json
```

#### conversation_id
- 会話開始時にUUID v4で生成する
- 1つのエージェントに対して複数の会話を持てる

#### session_id
- Claude Codeのセッション識別子
- conversation_idに紐づけて保存する
- Web UIからの会話継続時に `--resume` で使用する

#### JSONスキーマ
```json
{
  "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
  "agent_id": "adam",
  "created_at": "2026-03-24T10:00:00Z",
  "updated_at": "2026-03-24T10:05:00Z",
  "session_id": "a48950ae-2bfd-4ddc-b278-5756a2d1624b",
  "messages": [
    {
      "role": "user",
      "content": "こんにちは",
      "timestamp": "2026-03-24T10:00:00Z"
    },
    {
      "role": "assistant",
      "content": "こんにちは。何かお手伝いできることはありますか？",
      "timestamp": "2026-03-24T10:00:02Z"
    }
  ]
}
```

agent_idがない場合（エージェントなしの会話）は `"agent_id": null` とする。

### 3.2 処理フロー（メッセージ送信）

1. ユーザーがメッセージを送信する
2. 会話履歴をファイルから読み込む（新規会話の場合は空）
3. ConfigManagerからエージェント情報を取得する
4. Runner にエージェント情報と会話履歴（+新規メッセージ）を渡す
5. Runnerからストリーミングで応答を受け取る
6. 応答チャンクをSSEでクライアントに返す
7. 応答完了後、ユーザーメッセージとエージェント応答を会話履歴に追記して保存する

### 3.3 公開インターフェース

```python
class ChatManager:
    def __init__(self, config_manager: ConfigManager, runner: Runner, agents_dir: Path):
        pass

    async def send_message(
        self,
        agent_id: str,
        conversation_id: str | None,
        message: str,
    ) -> AsyncGenerator[ChatEvent, None]:
        """
        メッセージを送信し、応答をストリーミングで返す。
        conversation_idがNoneの場合は新規会話を作成する。
        yieldするイベント:
          - ChatEvent(type="conversation_id", data=conversation_id)  ※新規会話時のみ
          - ChatEvent(type="chunk", data=テキストチャンク)
          - ChatEvent(type="done", data=完全な応答テキスト)
        """

    def get_conversations(self, agent_id: str) -> list[ConversationSummary]:
        """エージェントの会話一覧を返す（新しい順）"""

    def get_history(self, agent_id: str, conversation_id: str) -> Conversation:
        """指定会話の全履歴を返す"""

    def delete_conversation(self, agent_id: str, conversation_id: str) -> None:
        """会話を削除する"""
```

#### データ型

```python
class ChatEvent(BaseModel):
    type: Literal["conversation_id", "chunk", "done"]
    data: str

class ConversationSummary(BaseModel):
    conversation_id: str
    agent_id: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    last_message: str          # 最後のメッセージの先頭100文字

class Conversation(BaseModel):
    conversation_id: str
    agent_id: str
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessage]

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    timestamp: datetime
```

### 3.4 CLI会話同期（Stopフック）

Claude Code CLIでの会話を、Web UIと同じ会話履歴に自動保存する。

#### 仕組み

Claude CodeのStopフックを使い、応答完了時にフックスクリプトが会話履歴を更新する。

#### Stopフックが受け取るデータ（stdin）
```json
{
  "session_id": "a48950ae-...",
  "cwd": "D:\\AI\\code\\kobito_agent\\agents\\adam",
  "last_assistant_message": "応答テキスト",
  "transcript_path": "C:\\Users\\...\\a48950ae-....jsonl",
  "hook_event_name": "Stop"
}
```

#### 処理フロー

1. stdinからJSONを読む
2. `cwd` からagent_idを特定する
   - cwdが `agents/{name}/` 配下 → agent_id = `{name}`
   - それ以外（プロジェクトルート等） → agent_id = null
3. `session_id` で該当する会話履歴ファイルを検索する
4. 見つからなければ新しい `conversation_id` で会話ファイルを作成し、`session_id` を紐づける
5. `transcript_path` のJSONLから最新のユーザー入力を取得する
6. `last_assistant_message` とセットで会話履歴に追記する
7. `updated_at` を更新して保存する

#### agent_id特定ロジック

```
cwd = "D:\AI\code\kobito_agent\agents\adam"
project_root = "D:\AI\code\kobito_agent"

cwdからproject_rootを除いた相対パスが "agents/{name}" で始まる場合:
  → agent_id = name
  → 保存先: agents/{name}/chat_history/
それ以外:
  → agent_id = null
  → 保存先: chat_history/
```

#### 重複追記の防止

transcript_pathのJSONLには全履歴が含まれる。フックは毎ターン発火するため、前回保存済みのメッセージを重複追記しないよう、会話履歴の既存メッセージ数と比較して差分のみ追記する。

#### フック設定（.claude/settings.json）
```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python D:/AI/code/kobito_agent/scripts/sync_chat.py"
          }
        ]
      }
    ]
  }
}
```

### 3.5 WEB UI会話通知（UserPromptSubmitフック）

WEB UIでの会話をCLI側に通知する。CLI→WEB UIの同期（3.4）と対をなす逆方向の仕組み。

#### 仕組み

Claude CodeのUserPromptSubmitフックを使い、ユーザーがCLIでプロンプトを送信するたびにフックスクリプトがchat_historyを確認し、WEB UI側で追加されたメッセージがあればCLIの標準出力に表示する。

#### 処理フロー

1. ユーザーがCLIでプロンプトを送信 → UserPromptSubmitフック発火
2. stdinからJSON（session_id, cwd等）を読む
3. `cwd` からagent_idを特定する（3.4と同じロジック）
4. `session_id` で該当する会話履歴ファイルを検索する
5. `.last_seen_cli` ファイルから前回確認済みのメッセージ位置を読む
6. 未確認メッセージのうち `source: "web"` のものを抽出する
7. 確認済み位置を更新して `.last_seen_cli` に保存する
8. WEB UIからのメッセージがあれば標準出力に表示する

#### 出力形式

```
[Web UIでの新しいやりとり]
ユーザー: いまWEBUI上から入力しています。
エージェント: 分かった。今あなたはWEB UI上からこのメッセージを入力している。
```

#### 確認済み位置の管理

- `.last_seen_cli` ファイルに、最後に確認したメッセージ数（整数）を保存する
- 保存先: `agents/{agent_id}/chat_history/.last_seen_cli`
- フック発火ごとに現在のメッセージ総数で更新する

#### フック設定（agents/{agent_id}/.claude/settings.json）

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python D:/AI/code/kobito_agent/scripts/check_new_messages.py"
          }
        ]
      }
    ]
  }
}
```

### 3.6 REST API

| メソッド | パス | 説明 |
|---------|------|------|
| POST | `/api/agents/{agent_id}/chat` | メッセージ送信（SSEストリーミング応答） |
| GET | `/api/agents/{agent_id}/conversations` | 会話一覧取得 |
| GET | `/api/agents/{agent_id}/conversations/{conversation_id}` | 会話履歴取得 |
| DELETE | `/api/agents/{agent_id}/conversations/{conversation_id}` | 会話削除 |

#### POST /api/agents/{agent_id}/chat

リクエスト:
```json
{
  "message": "こんにちは",
  "conversation_id": "550e8400-..."  // 任意。省略時は新規会話
}
```

レスポンス（SSE）:
```
event: conversation_id
data: 550e8400-e29b-41d4-a716-446655440000

event: chunk
data: こんに

event: chunk
data: ちは

event: done
data: こんにちは。何かお手伝いできることはありますか？
```

#### GET /api/agents/{agent_id}/conversations

レスポンス:
```json
[
  {
    "conversation_id": "550e8400-...",
    "agent_id": "adam",
    "created_at": "2026-03-24T10:00:00Z",
    "updated_at": "2026-03-24T10:05:00Z",
    "message_count": 4,
    "last_message": "こんにちは。何かお手伝いできることはありますか？"
  }
]
```

#### エラーレスポンス
- 存在しないagent_id → 404
- 存在しないconversation_id → 404
- messageが空 → 400

## 4. 非機能要件

- 会話履歴の保存はファイルI/Oで行う（DB不要）
- SSEストリーミングにより、最初のトークンが即座にクライアントに届く
- 会話履歴の最大サイズは制限しない（Phase 1では）

## 5. 考慮事項・制限事項

- 会話履歴の同時書き込み制御は行わない（1ユーザー前提）
- エージェント間チャットはPhase 4で追加する
- 記憶の想起・保存はPhase 5で追加する
- Phase 1では会話のトークン数が上限を超えた場合、LLM APIのエラーがそのまま返る

## 6. テスト方針

- ユニットテスト（pytest）でChatManagerをテストする
- Runnerはモックする
- 会話履歴ファイルの読み書きはtmpディレクトリでテストする
- SSEストリーミングはFastAPI TestClient + httpxでテストする
- 正常系: 新規会話、既存会話への追記、履歴取得、一覧取得
- 異常系: 存在しないエージェント、存在しない会話、空メッセージ

## 7. テスト項目

### メッセージ送信
- 新規会話でメッセージを送信すると、conversation_idイベントが返る
- 新規会話でメッセージを送信すると、チャンクイベントが返る
- 新規会話でメッセージを送信すると、doneイベントに完全な応答が含まれる
- 既存会話にメッセージを送信すると、会話履歴が引き継がれる
- 送信後、会話履歴ファイルにユーザーメッセージとエージェント応答が保存される

### 会話履歴
- get_historyで会話の全メッセージが時系列順で返る
- get_conversationsで会話一覧が新しい順で返る
- get_conversationsのlast_messageに最後のメッセージの先頭100文字が含まれる

### 会話削除
- delete_conversationで会話ファイルが削除される
- 削除後、get_conversationsの一覧に含まれない

### CLI会話同期
- 新規セッションで会話すると、新しいconversation_idで会話ファイルが作成される
- 既存セッションで会話すると、既存の会話ファイルに追記される
- cwdがagents/{name}/配下の場合、agent_idが正しく特定される
- cwdがプロジェクトルートの場合、agent_idがnullになりプロジェクトルートのchat_history/に保存される
- 同じターンのメッセージが重複追記されない
- session_idが会話ファイルに保存される

### WEB UI会話通知
- WEB UIで送信されたメッセージ（source: "web"）がCLIに表示される
- CLI側のメッセージ（source: "cli"）は通知対象にならない
- 未確認メッセージがない場合、何も出力されない
- .last_seen_cliが確認済み位置を正しく記録・更新する
- session_idが一致する会話ファイルが見つからない場合、何も出力されない

### エラーハンドリング
- 存在しないagent_idでメッセージ送信すると404が返る
- 存在しないconversation_idで履歴取得すると404が返る
- 空メッセージを送信すると400が返る

### REST API
- POST /api/agents/{agent_id}/chat がSSEストリーミングレスポンスを返す
- GET /api/agents/{agent_id}/conversations が会話一覧を返す
- GET /api/agents/{agent_id}/conversations/{id} が会話履歴を返す
- DELETE /api/agents/{agent_id}/conversations/{id} が204を返す
