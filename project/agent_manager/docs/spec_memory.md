# 仕様書: 6-1 memory

## 1. 概要

エージェントの記憶機能を提供するコンポーネント。
Mem0ベクトル検索システムを使用し、各エージェント専用のメモリストレージで記憶の保存・検索・想起を行う。思考サイクルやチャット時に関連記憶を自動想起し、エージェントの文脈理解を向上させる。

**この仕様の範囲**: Mem0ラッパークラスの実装、記憶の保存・検索・想起API、Web UI連携
**範囲外**: Mem0の内部実装、ベクトルモデルの選択・設定、記憶内容の妥当性判断

**対応デバイス**: サーバーサイド（PC）
**使用技術**: Python, Mem0, ベクトル検索、FastAPI

## 2. 補足資料

### 2.1 参照ドキュメント
- `CLAUDE.md` の記憶（Mem0）・動作フロー・Web UIの節
- Mem0公式ドキュメント: https://docs.mem0.ai/

### 2.2 外部依存
- Mem0パッケージ（`pip install mem0ai`）
- OpenAI API（埋め込みベクトル生成用）または互換サービス

## 3. 機能詳細

### 3.1 ディレクトリ構造

```
agent/
  {agent_name}/
    memory/              # Mem0データストレージ（エージェント専用）
      config.json        # Mem0設定
      vector_store/      # ベクトルデータベース
      metadata/          # メタデータファイル
```

### 3.2 Pydanticモデル

```python
class MemoryItem(BaseModel):
    id: str                        # 記憶ID（Mem0が自動生成）
    content: str                   # 記憶内容
    metadata: dict[str, Any]       # メタデータ（日時・ソース等）
    relevance_score: float | None  # 関連度スコア（検索時のみ）

class MemorySearchResult(BaseModel):
    query: str                     # 検索クエリ
    results: list[MemoryItem]      # 検索結果（関連度順）
    total_count: int               # 総記憶数

class MemoryConfig(BaseModel):
    vector_store_type: str = "chroma"    # ベクトルストア種類
    embedding_model: str = "text-embedding-ada-002"  # 埋め込みモデル
    max_results: int = 10                # 検索結果最大数
    relevance_threshold: float = 0.7     # 関連度閾値
```

### 3.3 処理ロジック

#### 記憶の保存
1. テキスト入力を受け取る
2. Mem0にテキストを渡し、自動的にベクトル化・保存
3. メタデータ（日時、ソース、セッションID等）を付与
4. 重複記憶の排除（Mem0の自動重複排除機能を使用）

#### 記憶の検索・想起
1. 検索クエリ（テキスト）を受け取る
2. Mem0でベクトル類似検索を実行
3. 関連度閾値を超える記憶のみ返す
4. 関連度順にソートして返す

#### 自動想起（思考サイクル・チャット時）
1. 現在の文脈（mission/task内容、会話履歴の要約）からクエリを生成
2. 記憶検索を実行し、関連記憶を取得
3. 取得した記憶をプロンプトに組み込む

### 3.4 公開インターフェース

```python
class MemoryManager:
    def __init__(self, agent_id: str, memory_dir: Path):
        """agent_idは識別用、memory_dirはagent/{name}/memory/のパス"""

    async def save_memory(self, content: str, metadata: dict[str, Any] = None) -> str:
        """記憶を保存し、記憶IDを返す"""

    async def search_memory(self, query: str, max_results: int = 10) -> MemorySearchResult:
        """クエリで記憶を検索し、関連記憶を返す"""

    async def recall_relevant_memories(self, context: str) -> list[MemoryItem]:
        """文脈から関連記憶を自動想起する（思考サイクル・チャット用）"""

    async def list_all_memories(self, limit: int = 100, offset: int = 0) -> list[MemoryItem]:
        """全記憶を一覧取得（Web UI用）"""

    async def get_memory(self, memory_id: str) -> MemoryItem:
        """記憶IDで特定の記憶を取得"""

    async def delete_memory(self, memory_id: str) -> bool:
        """記憶を削除（管理用）"""

    async def get_memory_stats(self) -> dict[str, int]:
        """記憶統計（総数、今日の追加数等）を取得"""
```

### 3.5 Runner・Chat統合

#### 思考サイクルでの自動想起
```python
# runner.pyの_build_prompt内で
memories = await memory_manager.recall_relevant_memories(
    f"Mission: {mission}\nCurrent task: {task}"
)
if memories:
    prompt += f"\n## 関連する記憶\n"
    for memory in memories:
        prompt += f"- {memory.content}\n"
```

#### チャット時の自動想起・記録
```python
# chat.pyで
# 1. 想起
memories = await memory_manager.recall_relevant_memories(user_message)
# 2. LLM呼び出し（記憶を含むプロンプト）
# 3. 記録
await memory_manager.save_memory(
    f"User: {user_message}\nAssistant: {response}",
    {"source": "chat", "timestamp": datetime.now().isoformat()}
)
```

### 3.6 REST API

| メソッド | パス | 説明 | レスポンス |
|---------|------|------|-----------|
| GET | `/api/agents/{agent_id}/memory` | 記憶一覧 | `MemoryItem[]` |
| POST | `/api/agents/{agent_id}/memory/search` | 記憶検索 | `MemorySearchResult` |
| POST | `/api/agents/{agent_id}/memory` | 記憶保存 | `{"memory_id": str}` |
| DELETE | `/api/agents/{agent_id}/memory/{memory_id}` | 記憶削除 | `{"success": bool}` |
| GET | `/api/agents/{agent_id}/memory/stats` | 記憶統計 | `{"total": int, "today": int}` |

#### POST /api/agents/{agent_id}/memory/search リクエスト例
```json
{
  "query": "プロジェクトの進捗",
  "max_results": 5
}
```

#### レスポンス例
```json
{
  "query": "プロジェクトの進捗",
  "results": [
    {
      "id": "mem_123",
      "content": "フェーズ4（定期トリガー）が完了し、次はフェーズ5のエージェント間通信に着手予定",
      "metadata": {
        "source": "autonomous_thinking",
        "timestamp": "2026-03-25T10:30:00+00:00",
        "session_id": "sess_456"
      },
      "relevance_score": 0.92
    }
  ],
  "total_count": 1
}
```

## 4. 非機能要件

- **パフォーマンス**: 記憶検索は500ms以内、記憶保存は100ms以内
- **スケーラビリティ**: エージェント1体あたり10,000記憶まで対応
- **プライバシー**: エージェント間で記憶を共有しない（完全分離）
- **永続性**: サーバー再起動後も記憶を保持

## 5. 考慮事項・制限事項

- **記憶判断はエージェント任せ**: 何を記憶するかの判断はエージェント自身が行う。システムは保存・検索機能のみ提供
- **Mem0依存**: Mem0の内部実装に依存するため、Mem0の仕様変更で影響を受ける可能性
- **埋め込みAPI コスト**: OpenAI API等の埋め込み生成でコストが発生
- **記憶内容の妥当性**: 誤った記憶や不要な記憶の自動削除は行わない

## 6. テスト方針

- **ユニットテスト**: MemoryManagerの全メソッドをモックのMem0でテスト
- **統合テスト**: 実際のMem0を使った記憶保存・検索・想起のテスト
- **パフォーマンステスト**: 大量記憶データでの検索速度測定
- **API テスト**: FastAPI TestClientでエンドポイントテスト
- **テストデータ**: サンプル記憶データセットを用意し、検索精度を検証

## 7. テスト項目

### 記憶保存
- 記憶を保存し、記憶IDが返される
- メタデータが正しく付与される
- 重複する記憶内容は自動統合される
- 空文字列や無効な入力でエラーになる

### 記憶検索・想起
- クエリで関連記憶が取得できる
- 関連度順にソートされている
- 関連度閾値以下の記憶は除外される
- 検索結果が最大件数以下になる
- 存在しないクエリで空の結果が返る

### 自動想起
- 思考サイクルで文脈に関連する記憶が想起される
- チャット時にユーザー入力に関連する記憶が想起される
- 想起された記憶がプロンプトに正しく組み込まれる

### エージェント分離
- エージェントAの記憶がエージェントBから見えない
- 異なるmemory_dirで完全に分離されている
- memory_dirが異なれば同じ記憶IDでも別の記憶

### REST API
- GET /api/agents/{id}/memory が記憶一覧を返す
- POST /api/agents/{id}/memory/search が検索結果を返す
- POST /api/agents/{id}/memory が記憶IDを返す
- DELETE /api/agents/{id}/memory/{id} が削除成功を返す
- GET /api/agents/{id}/memory/stats が統計を返す
- 存在しないagent_idで404エラーが返る
- 存在しないmemory_idで404エラーが返る

### パフォーマンス
- 記憶検索が500ms以内に完了する
- 記憶保存が100ms以内に完了する
- 1,000件の記憶データで検索速度が劣化しない