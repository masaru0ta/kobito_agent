# エージェント間通信システム仕様書

**作成日**: 2026-03-25
**更新日**: 2026-03-26
**作成者**: アダム
**フェーズ**: 5
**状態**: 実装中
**方式**: セッション呼び出し方式（MCPサーバーによるtool_use）

## 概要

kobito_agentシステムにおけるエージェント間の通信機能。各エージェントが独立した思考を保ちながら、MCPサーバーが提供する `call_agent` ツールを通じて他のエージェントを呼び出せる。

## 設計原則

### 1. シンプルな仕組み
- MCPサーバーが `call_agent` ツールを1つだけ提供する
- 既存のAPIエンドポイント `POST /api/agents/{from_id}/call/{to_id}` を内部で利用
- 新しい通信プロトコルは作らない

### 2. 同期処理
- エージェント間の会話は同期処理で応答を待つ
- 非同期処理による複雑性を排除
- 確実な応答受信を保証

### 3. 独立した思考の保持
- 各エージェントは完全に独立した思考コンテキストを持つ
- 1つのLLM呼び出しで複数エージェントを演じることを禁止
- 相手の内面（思考過程）は見えない

### 4. 安全制約
- **自分自身の呼び出し禁止** — ツール側でエラーにする
- **呼び出し階層は2まで** — A→B は可。A→B→C は可。A→B→C→D は不可
- ツール説明文にも制約を明記し、LLMにも伝える

## システム構成

### MCPサーバー（新規）

`project/agent_manager/mcp_call_agent.py` にMCPサーバーを実装。

**提供ツール**: `call_agent`

```
call_agent(agent_id: str, message: str)
```

- `agent_id`: 呼び出し先のエージェントID（ディレクトリ名）
- `message`: 送信するメッセージ

**ツール説明文**:
```
他のエージェントを呼び出して会話する。自分自身を呼び出すことはできない。
呼び出し先のエージェントがさらに別のエージェントを呼ぶことはできるが、
2階層までに制限される。
```

**内部処理**:
1. 呼び出し元のagent_idを環境変数 `KOBITO_CALLER_AGENT_ID` から取得
2. 呼び出し階層を環境変数 `KOBITO_CALL_DEPTH` から取得（デフォルト0）
3. 自分自身の呼び出しチェック → エラー
4. 階層チェック（depth >= 2）→ エラー
5. `POST http://localhost:8300/api/agents/{from_id}/call/{to_id}` を実行
6. 応答を返す

### 環境変数

| 変数名 | 目的 | 設定タイミング |
|--------|------|--------------|
| `KOBITO_CALLER_AGENT_ID` | 呼び出し元エージェントの識別 | runner.pyがclaude -p起動時に設定 |
| `KOBITO_CALL_DEPTH` | 現在の呼び出し階層 | MCPサーバーがAPI呼び出し時にインクリメント |

### MCPサーバー登録

`.mcp.json`（プロジェクトルート）:
```json
{
  "mcpServers": {
    "call_agent": {
      "command": "python",
      "args": ["project/agent_manager/mcp_call_agent.py"],
      "env": {}
    }
  }
}
```

### 既存コンポーネント（実装済み）

#### InterAgentSessionManager
```python
class InterAgentSessionManager:
    async def call_agent(self, from_id, to_id, message, session_id=None,
                        caller_conversation_id=None) -> CallResult
```

#### APIエンドポイント
```
POST /api/agents/{from_id}/call/{to_id}
```

#### 履歴管理
- 呼び出し先: `chat_history/` にチャット履歴として保存（`source: "agent:{from_id}"`）
- 呼び出し元: `caller_conversation_id` 指定時に呼び出し記録を追記

## Runner統合

### claude -p 起動時の環境変数設定

runner.pyの `_run_claude_stream` で、エージェントのclaude -p起動時に環境変数を設定する:

```python
env["KOBITO_CALLER_AGENT_ID"] = agent_info.agent_id
env["KOBITO_CALL_DEPTH"] = str(current_depth)
```

### APIエンドポイントの拡張

`POST /api/agents/{from_id}/call/{to_id}` に `call_depth` パラメータを追加。
InterAgentSessionManagerが相手のclaude -pを起動する際に、`KOBITO_CALL_DEPTH` をインクリメントして渡す。

## テスト項目

### MCPサーバー基本機能
- [ ] call_agentツールが正常にエージェントを呼び出せる
- [ ] 応答が正しく返される
- [ ] session_idでの継続会話が動作する

### 安全制約
- [ ] 自分自身を呼び出すとエラーになる
- [ ] 呼び出し階層が2を超えるとエラーになる
- [ ] 存在しないエージェントを呼び出すとエラーになる

### 環境変数
- [ ] KOBITO_CALLER_AGENT_IDが正しく設定される
- [ ] KOBITO_CALL_DEPTHが呼び出しごとにインクリメントされる

### 履歴管理
- [ ] 呼び出し先のchat_historyに会話が保存される
- [ ] source="agent:xxx"が正しく付与される

### 統合テスト
- [ ] チームエージェントがcall_agentでメンバーに振れる
- [ ] 振られたエージェントが応答を返す
- [ ] Web UIからチームに話しかけて、メンバーの応答が返る

## 実装順序

1. MCPサーバー実装（`mcp_call_agent.py`）
2. runner.pyの環境変数設定追加
3. APIの`call_depth`対応
4. `.mcp.json`登録
5. チームエージェントのCLAUDE.md更新
6. テスト実行
