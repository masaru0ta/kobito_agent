"""テスト共通フィクスチャ"""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml


@pytest.fixture
def agents_dir(tmp_path):
    """agents/ディレクトリを作成して返す"""
    d = tmp_path / "agents"
    d.mkdir()
    return d


@pytest.fixture
def adam_dir(agents_dir):
    """アダムのエージェントディレクトリを作成して返す"""
    d = agents_dir / "adam"
    d.mkdir()

    config = {"name": "アダム", "model": "claude-sonnet-4-20250514", "description": "システムの設計者であり管理者"}
    (d / "config.yaml").write_text(yaml.dump(config, allow_unicode=True), encoding="utf-8")
    (d / "CLAUDE.md").write_text("あなたはアダム。このシステムの設計者である。", encoding="utf-8")
    (d / "mission.md").write_text("このシステムを設計し、構築し、改善する。", encoding="utf-8")

    (d / "chat_history").mkdir()
    return d


@pytest.fixture
def eden_dir(agents_dir):
    """エデンのエージェントディレクトリを作成して返す"""
    d = agents_dir / "eden"
    d.mkdir()

    config = {"name": "エデン", "model": "claude-haiku-4-5-20251001", "description": "情報収集と分析を担当"}
    (d / "config.yaml").write_text(yaml.dump(config, allow_unicode=True), encoding="utf-8")

    (d / "chat_history").mkdir()
    return d


@pytest.fixture
def sample_conversation(adam_dir):
    """アダムのサンプル会話履歴を作成して返す"""
    conv_id = "550e8400-e29b-41d4-a716-446655440000"
    conversation = {
        "conversation_id": conv_id,
        "agent_id": "adam",
        "created_at": "2026-03-24T10:00:00Z",
        "updated_at": "2026-03-24T10:05:00Z",
        "messages": [
            {
                "role": "user",
                "content": "こんにちは",
                "timestamp": "2026-03-24T10:00:00Z",
            },
            {
                "role": "assistant",
                "content": "こんにちは。何かお手伝いできることはありますか？",
                "timestamp": "2026-03-24T10:00:02Z",
            },
        ],
    }
    filepath = adam_dir / "chat_history" / f"{conv_id}.json"
    filepath.write_text(json.dumps(conversation, ensure_ascii=False), encoding="utf-8")
    return conv_id


@pytest.fixture
def mock_runner():
    """Runnerのモックを返す。run_streamはAsyncGeneratorとして動作する"""

    class MockRunner:
        def __init__(self):
            self._response_chunks = ["テスト", "応答", "です。"]

        def set_chunks(self, chunks):
            self._response_chunks = chunks

        def build_messages(self, agent_info, messages):
            built = []
            if agent_info.system_prompt:
                built.append({"role": "system", "content": agent_info.system_prompt})
            for msg in messages:
                built.append({"role": msg.role, "content": msg.content})
            return built

        async def run(self, agent_info, messages):
            if not messages:
                raise ValueError("メッセージリストが空です")
            return "".join(self._response_chunks)

        async def run_stream(self, agent_info, messages):
            if not messages:
                raise ValueError("メッセージリストが空です")
            for chunk in self._response_chunks:
                yield chunk

    return MockRunner()
