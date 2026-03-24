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
