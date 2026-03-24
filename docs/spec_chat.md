# 仕様書: 1-3 chat

## 1. 概要

ユーザーとエージェントのチャット処理を担当するコンポーネント。
メッセージの送受信、会話履歴の永続化、およびチャットAPIエンドポイントを提供する。

**この仕様の範囲**: ユーザー×エージェントの1対1チャット、会話履歴の保存・取得、ストリーミング応答
**範囲外**: エージェント間チャット（Phase 4）、記憶の想起・保存（Phase 5）、複数人チャット

**使用技術**: Python, FastAPI (SSE), JSON

## 2. 補足資料

### 2.1 参照ドキュメント
- `CLAUDE.md` の動作フロー・チャットの節
- `docs/spec_config.md` — AgentInfo の定義
- `docs/spec_runner.md` — Runner の定義

## 3. 機能詳細

### 3.1 会話履歴の保存形式

会話履歴は `agents/{agent_id}/chat_history/` に保存する。

#### ファイル構造
```
agents/adam/chat_history/
  {conversation_id}.json    # 会話ごとに1ファイル
```

#### conversation_id
- 会話開始時にUUID v4で生成する
- 1つのエージェントに対して複数の会話を持てる

#### JSONスキーマ
```json
{
  "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
  "agent_id": "adam",
  "created_at": "2026-03-24T10:00:00Z",
  "updated_at": "2026-03-24T10:05:00Z",
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

### 3.4 REST API

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

### エラーハンドリング
- 存在しないagent_idでメッセージ送信すると404が返る
- 存在しないconversation_idで履歴取得すると404が返る
- 空メッセージを送信すると400が返る

### REST API
- POST /api/agents/{agent_id}/chat がSSEストリーミングレスポンスを返す
- GET /api/agents/{agent_id}/conversations が会話一覧を返す
- GET /api/agents/{agent_id}/conversations/{id} が会話履歴を返す
- DELETE /api/agents/{agent_id}/conversations/{id} が204を返す
