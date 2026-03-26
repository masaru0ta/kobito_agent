# Web UIエージェント間チャット実装計画

**作成日**: 2026-03-25
**作成者**: アダム
**ステータス**: 実装開始

## 概要

既存のWeb UIに「エージェント間チャット」機能を追加する。各エージェントペア間の専用チャット画面を提供し、手動メッセージ送信・履歴表示・新着通知を実現する。

## 現在の状況

### 完了済み
- フェーズ5 Phase 5.1: 基盤実装完了
  - メッセージデータ構造（MessageType/Priority enum）
  - InterAgentMessengerクラス
  - APIエンドポイント（send-message, get-messages, mark-as-read）
  - 26/26テスト全通過

### 実装対象
- **Phase 5.3: Web UI実装** ← 現在の作業

## 実装方針

### UI設計
新しいタブ「エージェント間」を追加し、既存のチャットタブと並行して配置する。

```
[チャット] [思考] [ミッション] [成果物] [設定] [エージェント間] ← 新規
```

### 機能要件
1. **エージェントペア選択**: 送信先エージェントを選択
2. **メッセージ履歴表示**: 過去のメッセージスレッドを表示
3. **手動メッセージ送信**: テキストボックスからメッセージ送信
4. **新着通知**: 未読メッセージ数のバッジ表示
5. **メッセージタイプ選択**: request/response/notification

## 実装計画

### 1. HTML構造拡張
- 新しいタブボタン追加
- エージェント間チャット用のmid-content追加
- エージェント選択UI
- メッセージ送信フォーム

### 2. JavaScript実装
- `js/inter_agent_chat.js`: 新規ファイル
- エージェント間メッセージAPI統合
- チャット履歴表示
- リアルタイム通知

### 3. CSS追加
- エージェント間チャット用スタイル
- 既存のチャットスタイルを再利用・拡張

### 4. API統合
既存APIを活用:
- `POST /api/agents/{from_id}/send-message`
- `GET /api/agents/{agent_id}/messages`
- `PUT /api/agents/{agent_id}/messages/{message_id}/read`

## 詳細設計

### UI構造
```html
<div class="mid-content" id="mid-inter-agent">
  <!-- エージェント選択 -->
  <div class="inter-agent-header">
    <select id="target-agent-select">
      <option value="">送信先を選択...</option>
    </select>
    <span id="unread-badge" class="unread-badge">3</span>
  </div>

  <!-- メッセージ履歴 -->
  <div class="inter-agent-messages" id="inter-agent-messages">
    <!-- チャット履歴表示エリア -->
  </div>

  <!-- 送信フォーム -->
  <div class="inter-agent-input">
    <div class="message-type-selector">
      <select id="message-type-select">
        <option value="request">質問・依頼</option>
        <option value="notification">通知</option>
        <option value="response">応答</option>
      </select>
    </div>
    <div class="input-wrapper">
      <textarea id="inter-agent-input" placeholder="メッセージを入力..."></textarea>
      <button id="btn-send-inter-agent">送信</button>
    </div>
  </div>
</div>
```

### メッセージ表示形式
```
[adam → eden] 2026-03-25 19:30
> 現在のユーザーニーズを教えてください。
タイプ: request | thread: abc-123

[eden → adam] 2026-03-25 19:35
> ユーザーは○○に関心があるようです。詳細は...
タイプ: response | thread: abc-123
```

### JavaScript模块結構
```javascript
const InterAgentChat = {
  init(),
  loadAgents(),
  selectTargetAgent(agentId),
  loadMessageHistory(targetAgentId),
  sendMessage(targetAgentId, content, messageType),
  refreshUnreadCount(),
  markAsRead(messageId),
  renderMessage(message),
  _formatMessage(message)
};
```

## 実装ステップ

### Step 1: HTML構造追加
- [ ] index.htmlに「エージェント間」タブ追加
- [ ] mid-inter-agent セクション追加
- [ ] エージェント選択・メッセージ送信フォーム

### Step 2: JavaScript実装
- [ ] inter_agent_chat.js新規作成
- [ ] タブ切り替え機能統合（app.js）
- [ ] API通信機能
- [ ] メッセージ履歴表示

### Step 3: スタイリング
- [ ] CSSでエージェント間チャット用スタイル追加
- [ ] 既存チャットUIとの一貫性確保
- [ ] レスポンシブ対応

### Step 4: テスト・統合
- [ ] 手動テスト（adam→eden送信）
- [ ] エラーハンドリング
- [ ] 未読通知機能
- [ ] パフォーマンス確認

## テスト項目

### 基本機能
- [ ] エージェント一覧が正しく表示される
- [ ] 送信先エージェントを選択できる
- [ ] メッセージを送信できる
- [ ] メッセージ履歴が表示される
- [ ] 未読メッセージ数が表示される

### エラーハンドリング
- [ ] 送信先未選択時のエラー表示
- [ ] メッセージ空欄時のバリデーション
- [ ] API通信エラー時の処理
- [ ] 存在しないエージェントの処理

### UX
- [ ] タブ切り替えがスムーズ
- [ ] メッセージ送信後の即座反映
- [ ] 長いメッセージの表示処理
- [ ] モバイル端末での操作性

## 今後の拡張

### Phase 5.4対応
- スレッド表示（thread_idによるグループ化）
- メッセージ検索機能
- 優先度表示
- 配送状態表示

### 運用機能
- メッセージエクスポート
- 履歴のクリーンアップ
- 通知設定

---

**次のアクション**: Step 1（HTML構造追加）から開始