"""自律思考 Web API のテスト（spec_runner.md セクション11準拠）"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


def _mock_subprocess_run(text, session_id="api-test-session"):
    """subprocess.run のモックを返す"""
    result_line = json.dumps({
        "type": "result", "subtype": "success",
        "result": text, "session_id": session_id,
    })
    output = f"{result_line}\n"

    def mock_run(cmd, **kwargs):
        m = MagicMock()
        m.returncode = 0
        m.stdout = output.encode("utf-8")
        m.stderr = b""
        return m

    return mock_run


@pytest.fixture
def adam_with_task(adam_dir):
    """task.md も持つアダム"""
    (adam_dir / "task.md").write_text("- [ ] タスク1", encoding="utf-8")
    return adam_dir


@pytest.fixture
def client(agents_dir, adam_dir, eden_dir):
    from httpx import ASGITransport, AsyncClient
    from server.app import create_app

    app = create_app(agents_dir=agents_dir)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ============================================================
# POST /api/agents/{agent_id}/think
# ============================================================


class TestThinkAPI:
    """POST /api/agents/{agent_id}/think のテスト"""

    async def test_think_returns_result(self, agents_dir, adam_with_task, eden_dir):
        """POST /api/agents/{agent_id}/think が ThinkResult を返す"""
        from httpx import ASGITransport, AsyncClient
        from server.app import create_app

        app = create_app(agents_dir=agents_dir)
        transport = ASGITransport(app=app)
        client = AsyncClient(transport=transport, base_url="http://test")

        response_text = "タスク1を完了しました。"
        with patch("subprocess.run", side_effect=_mock_subprocess_run(response_text)):
            resp = await client.post("/api/agents/adam/think")

        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == "adam"
        assert data["response"] == response_text
        assert data["success"] is True

    async def test_think_agent_not_found(self, client):
        """POST /api/agents/{agent_id}/think で存在しないエージェントに404"""
        resp = await client.post("/api/agents/nonexistent/think")
        assert resp.status_code == 404


# ============================================================
# GET /api/agents/{agent_id}/logs
# ============================================================


class TestLogsAPI:
    """思考ログ API のテスト"""

    @pytest.fixture
    def adam_with_logs(self, adam_dir):
        """ログファイルを持つアダム"""
        log_dir = adam_dir / "log"
        log_dir.mkdir()

        log1 = {
            "timestamp": "2026-03-25T10:00:00+00:00",
            "agent_id": "adam",
            "prompt": "プロンプト1",
            "response": "最初の応答です",
            "success": True,
            "error": None,
        }
        log2 = {
            "timestamp": "2026-03-25T11:00:00+00:00",
            "agent_id": "adam",
            "prompt": "プロンプト2",
            "response": "二番目の応答です",
            "success": False,
            "error": "エラー発生",
        }

        (log_dir / "20260325_100000.json").write_text(
            json.dumps(log1, ensure_ascii=False), encoding="utf-8"
        )
        (log_dir / "20260325_110000.json").write_text(
            json.dumps(log2, ensure_ascii=False), encoding="utf-8"
        )
        return adam_dir

    async def test_logs_list_newest_first(self, agents_dir, adam_with_logs, eden_dir):
        """GET /api/agents/{agent_id}/logs が新しい順でログ一覧を返す"""
        from httpx import ASGITransport, AsyncClient
        from server.app import create_app

        app = create_app(agents_dir=agents_dir)
        client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        )

        resp = await client.get("/api/agents/adam/logs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        # 新しい順
        assert data[0]["filename"] == "20260325_110000.json"
        assert data[1]["filename"] == "20260325_100000.json"
        assert data[0]["summary"] == "二番目の応答です"
        assert data[0]["success"] is False

    async def test_log_detail(self, agents_dir, adam_with_logs, eden_dir):
        """GET /api/agents/{agent_id}/logs/{filename} がログ詳細を返す"""
        from httpx import ASGITransport, AsyncClient
        from server.app import create_app

        app = create_app(agents_dir=agents_dir)
        client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        )

        resp = await client.get("/api/agents/adam/logs/20260325_100000.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["response"] == "最初の応答です"
        assert data["prompt"] == "プロンプト1"
        assert data["success"] is True

    async def test_logs_agent_not_found(self, client):
        """GET /api/agents/{agent_id}/logs で存在しないエージェントに404"""
        resp = await client.get("/api/agents/nonexistent/logs")
        assert resp.status_code == 404


# ============================================================
# GET /api/agents/{agent_id}/outputs
# ============================================================


class TestOutputsAPI:
    """成果物 API のテスト"""

    @pytest.fixture
    def adam_with_outputs(self, adam_dir):
        """成果物を持つアダム"""
        output_dir = adam_dir / "output"
        output_dir.mkdir()
        (output_dir / "report.md").write_text("# レポート\n内容です。", encoding="utf-8")
        (output_dir / "notes.md").write_text("# メモ\nメモ内容。", encoding="utf-8")
        (output_dir / "index.md").write_text(
            "- [report.md](./report.md) — レポート\n"
            "- [notes.md](./notes.md) — メモ\n",
            encoding="utf-8",
        )
        return adam_dir

    async def test_outputs_list(self, agents_dir, adam_with_outputs, eden_dir):
        """GET /api/agents/{agent_id}/outputs が成果物一覧を返す"""
        from httpx import ASGITransport, AsyncClient
        from server.app import create_app

        app = create_app(agents_dir=agents_dir)
        client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        )

        resp = await client.get("/api/agents/adam/outputs")
        assert resp.status_code == 200
        data = resp.json()
        filenames = [item["filename"] for item in data]
        assert "report.md" in filenames
        assert "notes.md" in filenames
        # index.md は含まない
        assert "index.md" not in filenames

    async def test_output_content(self, agents_dir, adam_with_outputs, eden_dir):
        """GET /api/agents/{agent_id}/outputs/{filename} が成果物内容を返す"""
        from httpx import ASGITransport, AsyncClient
        from server.app import create_app

        app = create_app(agents_dir=agents_dir)
        client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        )

        resp = await client.get("/api/agents/adam/outputs/report.md")
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "report.md"
        assert "# レポート" in data["content"]

    async def test_outputs_agent_not_found(self, client):
        """GET /api/agents/{agent_id}/outputs で存在しないエージェントに404"""
        resp = await client.get("/api/agents/nonexistent/outputs")
        assert resp.status_code == 404
