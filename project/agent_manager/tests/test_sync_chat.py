"""CLI会話同期（Stopフック）のテスト（spec_chat.md準拠）"""

import json
from pathlib import Path

import pytest


@pytest.fixture
def project_root(tmp_path):
    """プロジェクトルートを作成して返す"""
    # agents/adam を作成
    adam_dir = tmp_path / "agent" / "adam" / "chat_history"
    adam_dir.mkdir(parents=True)
    # プロジェクトルートの chat_history を作成
    (tmp_path / "chat_history").mkdir()
    return tmp_path


@pytest.fixture
def transcript_path(tmp_path):
    """Claude Codeのtranscript（JSONL）を作成して返す"""
    path = tmp_path / "session.jsonl"
    lines = [
        json.dumps({
            "type": "user",
            "message": {"role": "user", "content": "こんにちは"},
            "uuid": "msg-001",
            "timestamp": "2026-03-25T10:00:00Z",
            "sessionId": "session-aaa",
        }, ensure_ascii=False),
        json.dumps({
            "parentUuid": "msg-001",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "こんにちは！"}]},
            "uuid": "msg-002",
            "timestamp": "2026-03-25T10:00:01Z",
        }, ensure_ascii=False),
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@pytest.fixture
def make_hook_input(project_root, transcript_path):
    """Stopフックのstdin入力を生成するヘルパー"""
    def _make(cwd=None, session_id="session-aaa", last_assistant_message="こんにちは！"):
        if cwd is None:
            cwd = str(project_root / "agent" / "adam")
        return {
            "session_id": session_id,
            "cwd": cwd,
            "last_assistant_message": last_assistant_message,
            "transcript_path": str(transcript_path),
            "hook_event_name": "Stop",
        }
    return _make


# ============================================================
# sync_chat モジュールのインポート（実装後に有効になる）
# ============================================================

from scripts.sync_chat import sync_chat, resolve_agent_id


# ============================================================
# 新規セッション
# ============================================================


class TestNewSession:
    """新規セッションでの会話同期"""

    def test_creates_new_conversation_file(self, project_root, make_hook_input):
        """新規セッションで会話すると、新しいconversation_idで会話ファイルが作成される"""
        hook_input = make_hook_input()
        sync_chat(hook_input, project_root)

        chat_dir = project_root / "agent" / "adam" / "chat_history"
        files = list(chat_dir.glob("*.json"))
        assert len(files) == 1

        data = json.loads(files[0].read_text(encoding="utf-8"))
        assert data["conversation_id"] == files[0].stem
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][0]["content"] == "こんにちは"
        assert data["messages"][1]["role"] == "assistant"
        assert data["messages"][1]["content"] == "こんにちは！"

    def test_session_id_saved(self, project_root, make_hook_input):
        """session_idが会話ファイルに保存される"""
        hook_input = make_hook_input()
        sync_chat(hook_input, project_root)

        chat_dir = project_root / "agent" / "adam" / "chat_history"
        files = list(chat_dir.glob("*.json"))
        data = json.loads(files[0].read_text(encoding="utf-8"))
        assert data["session_id"] == "session-aaa"


# ============================================================
# 既存セッション
# ============================================================


class TestExistingSession:
    """既存セッションでの会話同期"""

    def test_appends_to_existing_conversation(self, project_root, make_hook_input, transcript_path):
        """既存セッションで会話すると、既存の会話ファイルに追記される"""
        # 1回目
        hook_input = make_hook_input()
        sync_chat(hook_input, project_root)

        # transcript に2ターン目を追記
        lines = transcript_path.read_text(encoding="utf-8").strip().split("\n")
        lines.append(json.dumps({
            "type": "user",
            "message": {"role": "user", "content": "元気？"},
            "uuid": "msg-003",
            "timestamp": "2026-03-25T10:01:00Z",
            "sessionId": "session-aaa",
        }, ensure_ascii=False))
        lines.append(json.dumps({
            "parentUuid": "msg-003",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "元気です！"}]},
            "uuid": "msg-004",
            "timestamp": "2026-03-25T10:01:01Z",
        }, ensure_ascii=False))
        transcript_path.write_text("\n".join(lines), encoding="utf-8")

        # 2回目
        hook_input2 = make_hook_input(last_assistant_message="元気です！")
        sync_chat(hook_input2, project_root)

        chat_dir = project_root / "agent" / "adam" / "chat_history"
        files = list(chat_dir.glob("*.json"))
        assert len(files) == 1  # ファイルは増えない

        data = json.loads(files[0].read_text(encoding="utf-8"))
        assert len(data["messages"]) == 4
        assert data["messages"][2]["content"] == "元気？"
        assert data["messages"][3]["content"] == "元気です！"

    def test_no_duplicate_messages(self, project_root, make_hook_input):
        """同じターンのメッセージが重複追記されない"""
        hook_input = make_hook_input()
        sync_chat(hook_input, project_root)
        # 同じ内容で再度呼ぶ（transcriptが変わっていない）
        sync_chat(hook_input, project_root)

        chat_dir = project_root / "agent" / "adam" / "chat_history"
        files = list(chat_dir.glob("*.json"))
        data = json.loads(files[0].read_text(encoding="utf-8"))
        assert len(data["messages"]) == 2  # 増えない


# ============================================================
# agent_id特定
# ============================================================


class TestResolveAgentId:
    """cwdからagent_idを特定するロジック"""

    def test_agents_subdir(self, project_root):
        """cwdがagents/{name}/配下の場合、agent_idが正しく特定される"""
        cwd = str(project_root / "agent" / "adam")
        assert resolve_agent_id(cwd, project_root) == "adam"

    def test_agents_deep_subdir(self, project_root):
        """cwdがagents/{name}/の深い階層でも、agent_idが正しく特定される"""
        cwd = str(project_root / "agent" / "adam" / "output")
        assert resolve_agent_id(cwd, project_root) == "adam"

    def test_project_root(self, project_root):
        """cwdがプロジェクトルートの場合、agent_idがNoneになる"""
        cwd = str(project_root)
        assert resolve_agent_id(cwd, project_root) is None

    def test_other_subdir(self, project_root):
        """cwdがagents/以外のサブディレクトリの場合、agent_idがNoneになる"""
        cwd = str(project_root / "server")
        assert resolve_agent_id(cwd, project_root) is None


# ============================================================
# エージェントなしの会話
# ============================================================


class TestNoAgent:
    """プロジェクトルートでの会話（エージェントなし）"""

    def test_saves_to_root_chat_history(self, project_root, make_hook_input):
        """cwdがプロジェクトルートの場合、プロジェクトルートのchat_history/に保存される"""
        hook_input = make_hook_input(cwd=str(project_root))
        sync_chat(hook_input, project_root)

        chat_dir = project_root / "chat_history"
        files = list(chat_dir.glob("*.json"))
        assert len(files) == 1

        data = json.loads(files[0].read_text(encoding="utf-8"))
        assert data["agent_id"] is None
        assert len(data["messages"]) == 2
