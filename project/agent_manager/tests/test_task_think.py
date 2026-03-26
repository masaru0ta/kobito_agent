"""タスク連動自律思考のテスト（spec_task_think.md 準拠）"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


def _make_client(agents_dir):
    from httpx import ASGITransport, AsyncClient
    from server.app import create_app

    app = create_app(agents_dir=agents_dir)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def adam_with_tasks(adam_dir):
    """タスクファイルを持つアダム"""
    tasks_dir = adam_dir / "tasks"
    tasks_dir.mkdir()

    # 承認済タスク（進捗50%）
    (tasks_dir / "task_001_approved.md").write_text(
        "# 承認済タスク\n\n"
        "**ステータス: 承認済**\n\n"
        "## チェックリスト\n"
        "- [x] 完了した項目\n"
        "- [ ] 未完了の項目\n",
        encoding="utf-8",
    )

    # 未承認タスク（進捗0%）
    (tasks_dir / "task_002_pending.md").write_text(
        "# 未承認タスク\n\n"
        "**ステータス: 未承認**\n\n"
        "## チェックリスト\n"
        "- [ ] 項目A\n"
        "- [ ] 項目B\n"
        "- [ ] 項目C\n",
        encoding="utf-8",
    )

    # 全完了タスク（進捗100%）
    (tasks_dir / "task_003_done.md").write_text(
        "# 全完了タスク\n\n"
        "**ステータス: 承認済**\n\n"
        "## チェックリスト\n"
        "- [x] 項目1\n"
        "- [x] 項目2\n",
        encoding="utf-8",
    )

    # ステータス行なしタスク
    (tasks_dir / "task_004_no_status.md").write_text(
        "# ステータスなし\n\n"
        "## チェックリスト\n"
        "- [ ] 項目\n",
        encoding="utf-8",
    )

    # index.md（一覧から除外されるべき）
    (tasks_dir / "index.md").write_text(
        "# タスク管理\nこれはindex。",
        encoding="utf-8",
    )

    return adam_dir


def _mock_think_stream_factory(session_id="mock-session-id"):
    """think_streamのモックを返すファクトリ"""
    async def mock_think_stream(agent_info, agent_dir, session_id=None, task_file=None):
        yield {"type": "result", "content": "完了", "log_path": "test.json",
               "success": True, "session_id": session_id or "mock-session-id"}
    return mock_think_stream


# ============================================================
# GET /api/agents/{agent_id}/tasks（タスク一覧）
# ============================================================


class TestTasksListAPI:
    """タスク一覧APIのテスト"""

    async def test_tasks_list(self, agents_dir, adam_with_tasks, eden_dir):
        """タスク一覧が返る（filename, title, status, progress等）"""
        client = _make_client(agents_dir)
        resp = await client.get("/api/agents/adam/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 4  # index.md除外で4件

        for task in data:
            assert "filename" in task
            assert "title" in task
            assert "status" in task
            assert "progress" in task
            assert "completed_tasks" in task
            assert "total_tasks" in task

    async def test_index_md_excluded(self, agents_dir, adam_with_tasks, eden_dir):
        """index.mdが一覧に含まれない"""
        client = _make_client(agents_dir)
        resp = await client.get("/api/agents/adam/tasks")
        filenames = [t["filename"] for t in resp.json()]
        assert "index.md" not in filenames

    async def test_progress_calculation(self, agents_dir, adam_with_tasks, eden_dir):
        """チェックリストから進捗率が正しく計算される"""
        client = _make_client(agents_dir)
        resp = await client.get("/api/agents/adam/tasks")
        data = {t["filename"]: t for t in resp.json()}

        assert data["task_001_approved.md"]["progress"] == 50
        assert data["task_001_approved.md"]["completed_tasks"] == 1
        assert data["task_001_approved.md"]["total_tasks"] == 2

        assert data["task_002_pending.md"]["progress"] == 0
        assert data["task_002_pending.md"]["total_tasks"] == 3

        assert data["task_003_done.md"]["progress"] == 100
        assert data["task_003_done.md"]["total_tasks"] == 2

    async def test_status_extraction(self, agents_dir, adam_with_tasks, eden_dir):
        """ステータスが本文から正しく抽出される"""
        client = _make_client(agents_dir)
        resp = await client.get("/api/agents/adam/tasks")
        data = {t["filename"]: t for t in resp.json()}

        assert data["task_001_approved.md"]["status"] == "承認済"
        assert data["task_002_pending.md"]["status"] == "未承認"
        assert data["task_004_no_status.md"]["status"] == "不明"

    async def test_empty_tasks_dir(self, agents_dir, adam_dir, eden_dir):
        """タスクディレクトリがない場合は空配列を返す"""
        client = _make_client(agents_dir)
        resp = await client.get("/api/agents/adam/tasks")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_tasks_agent_not_found(self, agents_dir, adam_dir, eden_dir):
        """存在しないエージェントに対して404を返す"""
        client = _make_client(agents_dir)
        resp = await client.get("/api/agents/nonexistent/tasks")
        assert resp.status_code == 404


# ============================================================
# GET /api/agents/{agent_id}/tasks/{filename}（タスク詳細）
# ============================================================


class TestTaskDetailAPI:
    """タスク詳細APIのテスト"""

    async def test_task_content(self, agents_dir, adam_with_tasks, eden_dir):
        """タスクの内容と進捗率が返る"""
        client = _make_client(agents_dir)
        resp = await client.get("/api/agents/adam/tasks/task_001_approved.md")
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "task_001_approved.md"
        assert "# 承認済タスク" in data["content"]
        assert data["progress"] == 50

    async def test_task_not_found(self, agents_dir, adam_with_tasks, eden_dir):
        """存在しないファイルに404を返す"""
        client = _make_client(agents_dir)
        resp = await client.get("/api/agents/adam/tasks/nonexistent.md")
        assert resp.status_code == 404


# ============================================================
# POST /api/agents/{agent_id}/think?task=xxx（承認チェック）
# ============================================================


class TestTaskThinkApprovalCheck:
    """タスク指定思考の承認チェックテスト

    全テストでrunnerをモックする（claude -pの実行を防ぐため）。
    承認チェックはrunner呼び出しの前にAPIレイヤーで行われるべき。
    """

    @pytest.fixture(autouse=True)
    def mock_runner(self):
        with patch("server.routes.think._get_runner") as mock_get:
            runner = AsyncMock()
            runner.think_stream = _mock_think_stream_factory()
            mock_get.return_value = runner
            yield runner

    async def test_approved_task_accepted(self, agents_dir, adam_with_tasks, eden_dir):
        """承認済タスクの実行が成功する"""
        client = _make_client(agents_dir)
        resp = await client.post("/api/agents/adam/think?task=task_001_approved.md")
        assert resp.status_code == 200

    async def test_pending_task_rejected(self, agents_dir, adam_with_tasks, eden_dir):
        """未承認タスクの実行が403で拒否される"""
        client = _make_client(agents_dir)
        resp = await client.post("/api/agents/adam/think?task=task_002_pending.md")
        assert resp.status_code == 403

    async def test_no_status_task_rejected(self, agents_dir, adam_with_tasks, eden_dir):
        """ステータス行がないタスクの実行が403で拒否される"""
        client = _make_client(agents_dir)
        resp = await client.post("/api/agents/adam/think?task=task_004_no_status.md")
        assert resp.status_code == 403

    async def test_nonexistent_task_404(self, agents_dir, adam_with_tasks, eden_dir):
        """存在しないタスクの実行が404を返す"""
        client = _make_client(agents_dir)
        resp = await client.post("/api/agents/adam/think?task=nonexistent.md")
        assert resp.status_code == 404


# ============================================================
# タスク単位セッション管理
# ============================================================


class TestTaskSessionManagement:
    """タスク単位のセッション管理テスト"""

    async def test_session_saved_per_task(self, agents_dir, adam_with_tasks, eden_dir):
        """タスク指定思考の完了後、.session_{filename}にセッションIDが保存される"""
        async def mock_stream(agent_info, agent_dir, session_id=None, task_file=None):
            yield {"type": "result", "content": "完了", "log_path": "test.json",
                   "success": True, "session_id": "new-session-123"}

        client = _make_client(agents_dir)
        with patch("server.routes.think._get_runner") as mock_get:
            runner = AsyncMock()
            runner.think_stream = mock_stream
            mock_get.return_value = runner
            resp = await client.post("/api/agents/adam/think?task=task_001_approved.md")
            assert resp.status_code == 200

        session_file = adam_with_tasks / ".session_task_001_approved.md"
        assert session_file.exists()
        assert session_file.read_text(encoding="utf-8").strip() == "new-session-123"

    async def test_session_resumed_for_same_task(self, agents_dir, adam_with_tasks, eden_dir):
        """同じタスクの再実行で前回のセッションIDが使われる"""
        session_file = adam_with_tasks / ".session_task_001_approved.md"
        session_file.write_text("previous-session-456", encoding="utf-8")

        captured = {}

        async def mock_stream(agent_info, agent_dir, session_id=None, task_file=None):
            captured["session_id"] = session_id
            captured["task_file"] = task_file
            yield {"type": "result", "content": "完了", "log_path": "test.json",
                   "success": True, "session_id": "previous-session-456"}

        client = _make_client(agents_dir)
        with patch("server.routes.think._get_runner") as mock_get:
            runner = AsyncMock()
            runner.think_stream = mock_stream
            mock_get.return_value = runner
            resp = await client.post("/api/agents/adam/think?task=task_001_approved.md")
            assert resp.status_code == 200

        assert captured.get("session_id") == "previous-session-456"

    async def test_traditional_mode_preserved(self, agents_dir, adam_with_tasks, eden_dir):
        """タスク指定なしの従来動作が維持される（.think_session_id使用）"""
        (adam_with_tasks / ".think_session_id").write_text("old-session-789", encoding="utf-8")

        captured = {}

        async def mock_stream(agent_info, agent_dir, session_id=None, task_file=None):
            captured["session_id"] = session_id
            yield {"type": "result", "content": "完了", "log_path": "test.json",
                   "success": True, "session_id": "old-session-789"}

        client = _make_client(agents_dir)
        with patch("server.routes.think._get_runner") as mock_get:
            runner = AsyncMock()
            runner.think_stream = mock_stream
            mock_get.return_value = runner
            resp = await client.post("/api/agents/adam/think?resume=true")
            assert resp.status_code == 200

        assert captured.get("session_id") == "old-session-789"
