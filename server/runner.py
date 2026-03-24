"""runnerコンポーネント — claude -p によるLLM呼び出しエンジン"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from typing import AsyncGenerator, Literal

from pydantic import BaseModel

from server.config import AgentInfo


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class Runner:
    def build_messages(self, agent_info: AgentInfo, messages: list[Message]) -> list[dict]:
        """LLMに送るメッセージ配列を組み立てる"""
        built = []

        if agent_info.system_prompt:
            built.append({"role": "system", "content": agent_info.system_prompt})

        for msg in messages:
            built.append({"role": msg.role, "content": msg.content})

        return built

    def _build_prompt(self, messages: list[Message]) -> str:
        """会話履歴を1つのプロンプト文字列に変換する"""
        parts = []
        for msg in messages:
            if msg.role == "user":
                parts.append(f"ユーザー: {msg.content}")
            else:
                parts.append(f"アシスタント: {msg.content}")
        return "\n\n".join(parts)

    @staticmethod
    def _find_claude() -> str:
        """claudeコマンドのフルパスを返す"""
        path = shutil.which("claude")
        if path is None:
            raise FileNotFoundError("claudeコマンドが見つかりません")
        return path

    def _build_cmd(self, agent_info: AgentInfo, prompt: str) -> list[str]:
        """claude -p コマンドの引数リストを組み立てる"""
        cmd = [
            self._find_claude(), "-p",
            "--output-format", "stream-json",
            "--verbose",
            "--no-session-persistence",
            "--model", agent_info.config.model,
        ]
        if agent_info.system_prompt:
            cmd.extend(["--system-prompt", agent_info.system_prompt])
        cmd.append(prompt)
        return cmd

    def _run_claude_sync(self, cmd: list[str]) -> str:
        """claude -p を同期的に実行してstdoutを返す"""
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=300,
        )
        if result.returncode != 0:
            stderr_text = result.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"claude -p 失敗: {stderr_text}")
        return result.stdout.decode("utf-8", errors="replace")

    async def _run_claude(self, agent_info: AgentInfo, messages: list[Message]) -> str:
        """claude -p を非同期で実行し、stdoutを返す"""
        prompt = self._build_prompt(messages)
        cmd = self._build_cmd(agent_info, prompt)
        return await asyncio.to_thread(self._run_claude_sync, cmd)

    def _parse_result(self, stdout: str) -> str:
        """stream-json出力からresultテキストを抽出する"""
        for line in stdout.strip().split("\n"):
            try:
                data = json.loads(line)
                if data.get("type") == "result":
                    return data.get("result", "")
            except json.JSONDecodeError:
                continue
        raise RuntimeError("claude -p から応答を取得できませんでした")

    async def run(self, agent_info: AgentInfo, messages: list[Message]) -> str:
        """非ストリーミング呼び出し。完全な応答テキストを返す"""
        if not messages:
            raise ValueError("メッセージリストが空です")

        stdout = await self._run_claude(agent_info, messages)
        return self._parse_result(stdout)

    async def run_stream(self, agent_info: AgentInfo, messages: list[Message]) -> AsyncGenerator[str, None]:
        """ストリーミング呼び出し。claude -pは一括応答なので、文単位で分割してyieldする"""
        if not messages:
            raise ValueError("メッセージリストが空です")

        stdout = await self._run_claude(agent_info, messages)
        result = self._parse_result(stdout)

        # 文単位で分割してyield（疑似ストリーミング）
        chunk_size = 50
        for i in range(0, len(result), chunk_size):
            yield result[i:i + chunk_size]
