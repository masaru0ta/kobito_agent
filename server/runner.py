"""runnerコンポーネント — claude -p によるLLM呼び出しエンジン"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncGenerator, Literal

from pydantic import BaseModel

from server.config import AgentInfo


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


@dataclass
class RunResult:
    """claude -p の実行結果"""
    text: str
    session_id: str


class Runner:
    def build_messages(self, agent_info: AgentInfo, messages: list[Message]) -> list[dict]:
        """LLMに送るメッセージ配列を組み立てる"""
        built = []

        if agent_info.system_prompt:
            built.append({"role": "system", "content": agent_info.system_prompt})

        for msg in messages:
            built.append({"role": msg.role, "content": msg.content})

        return built

    @staticmethod
    def _find_claude() -> str:
        """claudeコマンドのフルパスを返す"""
        path = shutil.which("claude")
        if path is None:
            raise FileNotFoundError("claudeコマンドが見つかりません")
        return path

    def _build_cmd(self, agent_info: AgentInfo, session_id: str | None = None) -> list[str]:
        """claude -p コマンドの引数リストを組み立てる（プロンプトはstdinで渡す）"""
        cmd = [
            self._find_claude(), "-p",
            "--output-format", "stream-json",
            "--verbose",
            "--model", agent_info.config.model,
        ]
        if session_id:
            cmd.extend(["--resume", session_id])
        else:
            if agent_info.system_prompt:
                cmd.extend(["--system-prompt", agent_info.system_prompt])
        return cmd

    def _run_claude_sync(self, cmd: list[str], prompt: str, cwd: Path | None = None) -> str:
        """claude -p を同期的に実行してstdoutを返す。プロンプトはstdinで渡す"""
        result = subprocess.run(
            cmd,
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=300,
            cwd=cwd,
        )
        if result.returncode != 0:
            stderr_text = result.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"claude -p 失敗: {stderr_text}")
        return result.stdout.decode("utf-8", errors="replace")

    async def _run_claude(self, agent_info: AgentInfo, prompt: str, session_id: str | None = None) -> str:
        """claude -p を非同期で実行し、stdoutを返す。cwdはエージェントのディレクトリ"""
        cmd = self._build_cmd(agent_info, session_id)
        cwd = Path("agents") / agent_info.agent_id
        return await asyncio.to_thread(self._run_claude_sync, cmd, prompt, cwd)

    def _parse_result(self, stdout: str) -> RunResult:
        """stream-json出力からresultテキストとsession_idを抽出する"""
        result_text = None
        session_id = None

        for line in stdout.strip().split("\n"):
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            if data.get("type") == "result":
                result_text = data.get("result", "")
                session_id = data.get("session_id", "")

        if result_text is None:
            raise RuntimeError("claude -p から応答を取得できませんでした")

        return RunResult(text=result_text, session_id=session_id or "")

    async def run(self, agent_info: AgentInfo, messages: list[Message], session_id: str | None = None) -> RunResult:
        """非ストリーミング呼び出し。RunResult（テキスト+session_id）を返す"""
        if not messages:
            raise ValueError("メッセージリストが空です")

        prompt = messages[-1].content
        stdout = await self._run_claude(agent_info, prompt, session_id)
        return self._parse_result(stdout)

    async def run_stream(
        self, agent_info: AgentInfo, messages: list[Message], session_id: str | None = None
    ) -> AsyncGenerator[str | RunResult, None]:
        """ストリーミング呼び出し。テキストチャンクをyieldし、最後にRunResultをyieldする"""
        if not messages:
            raise ValueError("メッセージリストが空です")

        prompt = messages[-1].content
        stdout = await self._run_claude(agent_info, prompt, session_id)
        run_result = self._parse_result(stdout)

        chunk_size = 50
        for i in range(0, len(run_result.text), chunk_size):
            yield run_result.text[i:i + chunk_size]

        # 最後にRunResultをyieldしてsession_idを呼び出し元に伝える
        yield run_result
