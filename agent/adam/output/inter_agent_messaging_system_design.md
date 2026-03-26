# エージェント間メッセージ配送システム詳細設計

**作成日**: 2026-03-25
**作成者**: アダム
**対象**: Phase 5.1 基盤実装

## 概要

エージェント間通信の基盤となるメッセージ配送システムの詳細設計。独立した思考コンテキストを保ちながら、効率的な非同期メッセージ交換を実現する。

## 1. InterAgentMessengerクラス設計

### 1.1 クラス構造
```python
class InterAgentMessenger:
    """エージェント間メッセージ配送を管理"""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.agents_dir = project_root / "agent"

    def send_message(self, message: InterAgentMessage) -> MessageResult
    def get_inbox_messages(self, agent_id: str, status: str = "unread") -> List[InterAgentMessage]
    def mark_as_read(self, agent_id: str, message_id: str) -> bool
    def archive_message(self, agent_id: str, message_id: str) -> bool
    def validate_agent_exists(self, agent_id: str) -> bool
    def create_message_dirs(self, agent_id: str) -> None
```

### 1.2 メッセージデータクラス
```python
@dataclass
class InterAgentMessage:
    message_id: str
    from_agent_id: str
    to_agent_id: str
    content: str
    sent_at: datetime
    message_type: MessageType  # request, response, notification
    thread_id: Optional[str] = None
    priority: Priority = Priority.NORMAL  # high, normal, low
    status: MessageStatus = MessageStatus.UNREAD  # unread, read, archived

    def to_json(self) -> str
    @classmethod
    def from_json(cls, json_str: str) -> "InterAgentMessage"

@enum
class MessageType(Enum):
    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"

@enum
class Priority(Enum):
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"

@enum
class MessageStatus(Enum):
    UNREAD = "unread"
    READ = "read"
    ARCHIVED = "archived"
```

### 1.3 配送結果クラス
```python
@dataclass
class MessageResult:
    success: bool
    message_id: str
    delivered_at: Optional[datetime] = None
    error_message: Optional[str] = None
```

## 2. メッセージキューシステム設計

### 2.1 ディレクトリ構造
```
agent/{agent_id}/messages/
├── inbox/              # 受信メッセージ（未読・既読）
│   ├── {message_id}.json
│   └── .processed/     # 処理済みマーカー用（オプション）
├── outbox/            # 送信履歴
│   └── {message_id}.json
└── archive/           # アーカイブ済み
    └── {message_id}.json
```

### 2.2 ファイル操作設計

#### 送信処理
1. **メッセージID生成**: `uuid.uuid4().hex`
2. **送信者のoutboxに保存**: 送信履歴として記録
3. **受信者のinboxに配送**: 原子的な書き込み操作
4. **配送結果を返す**: 成功/失敗とタイムスタンプ

#### 受信処理
1. **inboxスキャン**: `.json`ファイルを更新時刻順でソート
2. **メッセージ読み込み**: JSON→InterAgentMessageへデシリアライズ
3. **ステータスフィルタ**: unread, read, archivedで絞り込み

#### アーカイブ処理
1. **inboxからarchiveに移動**: `shutil.move()`で原子的移動
2. **ステータス更新**: `status: "archived"`に変更

### 2.3 エラー処理設計

#### ファイルシステムエラー
- **存在しないエージェント**: 404 Agent Not Found
- **ディスク容量不足**: 507 Insufficient Storage
- **権限エラー**: 403 Permission Denied
- **ファイル破損**: JSONデシリアライズ失敗時はskip

#### バリデーションエラー
- **メッセージサイズ制限**: 最大10MB
- **必須フィールドチェック**: from_agent_id, to_agent_id, content
- **agent_id形式チェック**: 英数字とハイフンのみ

### 2.4 パフォーマンス考慮

#### ファイル数制限
- **inbox**: 最大1000件、超過時は自動アーカイブ
- **archive**: 日付別サブディレクトリ（`YYYY-MM-DD/`）

#### キャッシュ設計
```python
class MessageCache:
    """頻繁なアクセスを避けるためのメモリキャッシュ"""

    def __init__(self, cache_ttl: int = 300):  # 5分キャッシュ
        self._inbox_cache: Dict[str, List[InterAgentMessage]] = {}
        self._cache_expiry: Dict[str, datetime] = {}
        self.cache_ttl = cache_ttl

    def get_inbox(self, agent_id: str) -> Optional[List[InterAgentMessage]]
    def invalidate(self, agent_id: str) -> None
    def _is_expired(self, agent_id: str) -> bool
```

## 3. API設計詳細

### 3.1 REST エンドポイント

#### メッセージ送信
```
POST /api/agents/{from_agent_id}/send-message
Content-Type: application/json

{
  "to_agent_id": "eden",
  "content": "現在のユーザーニーズを教えてください。",
  "message_type": "request",
  "priority": "normal",
  "thread_id": null
}
```

**応答**:
```json
{
  "success": true,
  "message_id": "abc123def456",
  "delivered_at": "2026-03-25T19:30:00Z"
}
```

#### 受信メッセージ取得
```
GET /api/agents/{agent_id}/messages?status=unread&limit=10&offset=0
```

**応答**:
```json
{
  "messages": [...],
  "total_count": 25,
  "unread_count": 3
}
```

#### メッセージ操作
```
PUT /api/agents/{agent_id}/messages/{message_id}/read
DELETE /api/agents/{agent_id}/messages/{message_id}  # アーカイブ
```

### 3.2 FastAPI実装例

```python
from fastapi import APIRouter, HTTPException
from .messenger import InterAgentMessenger
from .models import SendMessageRequest, MessageResponse

router = APIRouter(prefix="/api/agents")

@router.post("/{from_agent_id}/send-message")
async def send_message(
    from_agent_id: str,
    request: SendMessageRequest
) -> MessageResponse:
    messenger = InterAgentMessenger(app.project_root)

    # バリデーション
    if not messenger.validate_agent_exists(from_agent_id):
        raise HTTPException(404, f"Agent {from_agent_id} not found")
    if not messenger.validate_agent_exists(request.to_agent_id):
        raise HTTPException(404, f"Target agent {request.to_agent_id} not found")

    # メッセージ作成・配送
    message = InterAgentMessage(
        message_id=uuid4().hex,
        from_agent_id=from_agent_id,
        to_agent_id=request.to_agent_id,
        content=request.content,
        sent_at=datetime.utcnow(),
        message_type=MessageType(request.message_type),
        thread_id=request.thread_id,
        priority=Priority(request.priority)
    )

    result = messenger.send_message(message)

    if result.success:
        return MessageResponse(
            success=True,
            message_id=result.message_id,
            delivered_at=result.delivered_at
        )
    else:
        raise HTTPException(500, result.error_message)
```

## 4. 実装ロードマップ

### Week 1: コア実装
1. **メッセージデータ構造**: dataclass, enum定義
2. **InterAgentMessenger基本機能**: send_message, get_inbox_messages
3. **ファイル操作**: JSON保存、読み込み、移動
4. **単体テスト**: 基本的な送受信テスト

### Week 2: API統合
1. **FastAPIエンドポイント**: POST send-message, GET messages
2. **バリデーション**: agent存在確認、メッセージ形式チェック
3. **エラーハンドリング**: 適切なHTTPステータスコード
4. **統合テスト**: APIレベルのテスト

### Week 3: 高度な機能
1. **メッセージキャッシュ**: パフォーマンス最適化
2. **自動アーカイブ**: 古いメッセージのクリーンアップ
3. **メトリクス**: 配送成功率、レスポンス時間
4. **運用テスト**: 負荷テスト、長時間稼働テスト

## 5. 次のステップ

1. **GitHub Issue作成**: Phase 5.1の実装タスクをIssue登録
2. **TDD開始**: テストケース先行作成
3. **プロトタイプ実装**: 最小機能で動作確認
4. **Runner統合準備**: 思考サイクルとの連携設計

---

**Status**: 設計完了 → Issue作成準備中