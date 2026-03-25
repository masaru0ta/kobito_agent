# 仕様書: 2-1 設定管理

## 1. 概要

Web UIからエージェントの設定を閲覧・編集する機能。

**編集対象**:
- `config.yaml` — 名前、モデル、説明
- `CLAUDE.md` — システムプロンプト（人格の定義）

**この仕様の範囲**: 設定の読み込み・編集API、設定画面UI
**範囲外**: mission.md / task.md の編集（エージェントが自律管理する）、エージェントの新規作成・削除

**使用技術**: Python (FastAPI), HTML, CSS, JavaScript (バニラ)

## 2. 補足資料

### 2.1 モックアップ

HTMLモックアップ: `docs/mockup_phase2.html`

### 2.2 参照ドキュメント
- `docs/spec_config.md` — AgentInfo, AgentConfig の定義
- `docs/spec_web.md` — 既存のUI構成

## 3. 機能詳細

### 3.1 UI設計

#### 画面遷移

チャット画面のヘッダーに歯車アイコン付き「設定」ボタンを追加する。クリックするとメインエリアがチャットから設定画面に切り替わる。「チャットに戻る」ボタンで元に戻る。

ヘッダーのボタン表示ルール:
- **チャット画面**: 「設定」ボタン + 「新規会話」ボタンを表示。「チャットに戻る」は非表示
- **設定画面**: 「チャットに戻る」ボタンのみ表示。「設定」「新規会話」は非表示

サイドバーは共通（エージェント一覧・会話履歴）。設定画面表示中もエージェントの切り替えは可能。

#### 設定画面の構成

```
┌─────────────────────────────────────────┐
│ ヘッダー: エージェント名 + 「チャットに戻る」  │
├─────────────────────────────────────────┤
│                                         │
│  基本設定                                │
│  ┌───────────────────────────────────┐  │
│  │ 名前:    [アダム               ]  │  │
│  │ モデル:  [claude-sonnet-4-... ▼]  │  │
│  │ 説明:    [システムの設計者であ...]  │  │
│  └───────────────────────────────────┘  │
│                                         │
│  システムプロンプト（CLAUDE.md）           │
│  ┌───────────────────────────────────┐  │
│  │                                   │  │
│  │ あなたは「アダム」。このシステム    │  │
│  │ （kobito_agent）の設計者であり     │  │
│  │ 管理者である。...                  │  │
│  │                                   │  │
│  │                                   │  │
│  └───────────────────────────────────┘  │
│                                         │
│                        [保存] [リセット]  │
│                                         │
└─────────────────────────────────────────┘
```

#### フォーム要素

| フィールド | 要素 | バリデーション | ヒントテキスト |
|-----------|------|--------------|---------------|
| 名前 | テキスト入力 | 必須。空不可 | なし |
| モデル | テキスト入力 | 必須。空不可 | 「例: claude-sonnet-4-20250514, claude-haiku-4-5-20251001」 |
| 説明 | テキスト入力 | 任意。空可 | なし |
| システムプロンプト | テキストエリア（大、等幅フォント） | 任意。空可 | 「Markdown形式で記述できます」 |

### 3.2 処理フロー

#### 設定画面表示時
1. ヘッダーの「設定」ボタンをクリック
2. メインエリアをチャットから設定画面に切り替える
3. 現在選択中のエージェント情報（既に `GET /api/agents/{id}` で取得済み）をフォームに反映

#### 設定保存時
1. 「保存」ボタンをクリック
2. バリデーション（名前・モデルが空でないこと）
3. `PUT /api/agents/{agent_id}/config` を呼ぶ（config.yaml の更新）
4. `PUT /api/agents/{agent_id}/system-prompt` を呼ぶ（CLAUDE.md の更新）
5. 成功: 保存完了のフィードバックを表示（ボタンの色変更 + テキスト「保存しました」、2秒後に元に戻る）
6. 失敗: エラーメッセージを表示
7. サイドバーのエージェント一覧を再取得して反映（名前・説明の変更を反映）

#### リセット時
1. 「リセット」ボタンをクリック
2. フォームの内容を最後に保存された値に戻す

#### エージェント切り替え時（設定画面表示中）
1. 未保存の変更がある場合、確認ダイアログ「変更が保存されていません。破棄しますか？」
2. OK → 切り替え、キャンセル → 元のエージェントに留まる

### 3.3 REST API

#### PUT /api/agents/{agent_id}/config

config.yaml を更新する。

**リクエスト**:
```json
{
  "name": "アダム",
  "model": "claude-sonnet-4-20250514",
  "description": "システムの設計者であり管理者"
}
```

**バリデーション**:
- `name` が空 → 400
- `model` が空 → 400

**処理**:
1. 現在の config.yaml を読み込む
2. リクエストのフィールドで上書きする
3. config.yaml に書き戻す

**レスポンス** (200):
```json
{
  "agent_id": "adam",
  "config": {
    "name": "アダム",
    "model": "claude-sonnet-4-20250514",
    "description": "システムの設計者であり管理者"
  }
}
```

**エラー**:
- 404: エージェントが見つからない
- 400: バリデーションエラー

#### PUT /api/agents/{agent_id}/system-prompt

CLAUDE.md を更新する。

**リクエスト**:
```json
{
  "content": "あなたは「アダム」。このシステム（kobito_agent）の..."
}
```

**処理**:
1. `agents/{agent_id}/CLAUDE.md` にリクエストの `content` を書き込む
2. `content` が空文字列の場合、ファイルを空にする（削除はしない）

**レスポンス** (200):
```json
{
  "agent_id": "adam",
  "content": "あなたは「アダム」。このシステム（kobito_agent）の..."
}
```

**エラー**:
- 404: エージェントが見つからない

### 3.4 ConfigManager への追加メソッド

```python
class ConfigManager:
    # 既存メソッド（Phase 1）
    def list_agents(self) -> list[AgentInfo]: ...
    def get_agent(self, agent_id: str) -> AgentInfo: ...

    # Phase 2 追加
    def update_config(self, agent_id: str, name: str, model: str, description: str) -> AgentConfig:
        """config.yaml を更新する。更新後の AgentConfig を返す"""

    def update_system_prompt(self, agent_id: str, content: str) -> None:
        """CLAUDE.md を更新する"""
```

### 3.5 静的ファイル構成（追加分）

```
server/static/
  js/
    settings.js     # 設定画面の表示・保存処理
```

## 4. 非機能要件

- config.yaml の書き込みは排他制御しない（同時編集は想定しない）
- 保存後にサーバーのホットリロードが走る可能性がある（config.yamlはserver/外なので影響なし）

## 5. 考慮事項・制限事項

- エージェントの新規作成・削除はこのフェーズでは提供しない（ディレクトリを手動で作成する）
- config.yaml にPhase 4以降で追加されるフィールド（trigger等）がある場合、それらを消さないように上書き時は既存の内容をマージする
- モデルIDの妥当性チェック（実在するモデルか）は行わない

## 6. テスト方針

- ConfigManager の update_config / update_system_prompt をユニットテストする
- REST API を httpx + FastAPI TestClient でテストする
- UI は Playwright MCP で E2E テストする

## 7. テスト項目

### ConfigManager
- [ ] update_config で config.yaml の name が更新される
- [ ] update_config で config.yaml の model が更新される
- [ ] update_config で config.yaml の description が更新される
- [ ] update_config で name が空の場合 ValueError が送出される
- [ ] update_config で model が空の場合 ValueError が送出される
- [ ] update_config で存在しないエージェントに対して AgentNotFoundError が送出される
- [ ] update_config で config.yaml の未知のフィールドが保持される（将来の trigger 等を消さない）
- [ ] update_system_prompt で CLAUDE.md の内容が更新される
- [ ] update_system_prompt で空文字列を渡すと CLAUDE.md が空になる
- [ ] update_system_prompt で存在しないエージェントに対して AgentNotFoundError が送出される
- [ ] update_system_prompt で CLAUDE.md が存在しない場合、新規作成される

### REST API
- [ ] PUT /api/agents/{agent_id}/config が 200 と更新後の config を返す
- [ ] PUT /api/agents/{agent_id}/config で name が空の場合 400 を返す
- [ ] PUT /api/agents/{agent_id}/config で model が空の場合 400 を返す
- [ ] PUT /api/agents/{agent_id}/config で存在しない agent_id に対して 404 を返す
- [ ] PUT /api/agents/{agent_id}/system-prompt が 200 と更新後の内容を返す
- [ ] PUT /api/agents/{agent_id}/system-prompt で存在しない agent_id に対して 404 を返す
- [ ] 保存後に GET /api/agents/{agent_id} で更新された値が取得できる

### UI（Playwright）
- [ ] ヘッダーに「設定」ボタンが表示される
- [ ] 「設定」ボタンをクリックすると設定画面が表示される
- [ ] 設定画面にエージェントの名前・モデル・説明・システムプロンプトが表示される
- [ ] 名前を変更して保存すると、サイドバーのエージェント名が更新される
- [ ] 説明を変更して保存すると、サイドバーの説明が更新される
- [ ] システムプロンプトを変更して保存できる
- [ ] 保存成功時に「保存しました」のフィードバックが表示される
- [ ] 名前を空にして保存するとエラーが表示される
- [ ] 「リセット」ボタンで変更が元に戻る
- [ ] 「チャットに戻る」ボタンでチャット画面に戻る
- [ ] 未保存の変更がある状態でエージェントを切り替えると確認ダイアログが出る
