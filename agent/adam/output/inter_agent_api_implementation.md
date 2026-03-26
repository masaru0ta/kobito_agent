# エージェント間通信APIエンドポイント実装

## 実装日時
2026-03-25 - Phase 5.1実装進捗

## 概要
Phase 5.1の一環として、エージェント間通信用のAPIエンドポイントを完全実装した。InterAgentMessengerクラスを活用し、RESTful APIでエージェント間のメッセージ送受信が可能になった。

## 実装されたAPIエンドポイント

### 1. メッセージ送信
**POST** `/api/agents/{from_id}/send-message`

**リクエスト**:
```json
{
  "to_agent_id": "eden",
  "content": "Hello Eden",
  "message_type": "request",  // request, response, notification
  "priority": "normal",       // high, normal, low
  "thread_id": "optional-thread-id"
}
```

**レスポンス**:
```json
{
  "message_id": "generated-uuid",
  "from_agent_id": "adam",
  "to_agent_id": "eden",
  "sent_at": "2026-03-25T10:30:00Z",
  "thread_id": "thread-uuid",
  "status": "sent"
}
```

### 2. 未読メッセージ取得
**GET** `/api/agents/{agent_id}/messages`

**レスポンス**: メッセージオブジェクトの配列（送信時刻順）

### 3. メッセージ既読処理
**PUT** `/api/agents/{agent_id}/messages/{message_id}/read`

inboxからarchiveにメッセージを移動し、既読状態にする。

### 4. メッセージ履歴取得
**GET** `/api/agents/{agent_id}/conversations/{other_id}/history?limit=50`

2つのエージェント間の全メッセージ履歴を時刻順で取得。

## 技術的特徴

### エラーハンドリング
- 404: エージェントが存在しない
- 400: リクエストパラメーターのバリデーション失敗
- 500: ファイルI/O操作エラー

### データ構造
- **MessageType** enum: request, response, notification
- **Priority** enum: high, normal, low
- **InterAgentMessage** dataclass: 型安全なメッセージ構造

### 永続化
- ファイルベースのメッセージキュー
- 各エージェントのディレクトリ構造:
  ```
  agent/{agent_id}/messages/
    inbox/     # 未読メッセージ
    outbox/    # 送信履歴
    archive/   # 既読メッセージ
  ```

## 動作確認

### テスト結果
- InterAgentMessengerテスト: **26/26 PASSED** ✓
- サーバーアプリケーション起動テスト: **SUCCESS** ✓

### 統合確認
- APIエンドポイントがapp.pyに正常に統合された
- InterAgentMessengerのインスタンスが適切に作成されている
- 必要なimportとリクエストモデルが追加されている

## 次のステップ
Phase 5.1の残りタスク：
1. **メッセージキュー・配送機能の実装** ← 次の実装対象
2. Web UIでのエージェント間チャット表示
3. 動作テスト・バリデーション

## 設計上の利点
- RESTful設計によるシンプルなAPI
- InterAgentMessengerの既存機能を最大活用
- 型安全性（enum + dataclass）
- 包括的なエラーハンドリング
- 拡張性を考慮した設計

エージェント間通信の基盤APIが完成し、他のエージェントとのプログラム的な対話が可能になった。