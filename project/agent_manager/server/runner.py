"""runnerコンポーネント — claude -p によるLLM呼び出しエンジン"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
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


@dataclass
class ThinkResult:
    """自律思考の結果"""
    agent_id: str
    response: str
    log_path: str | None
    success: bool
    error: str | None


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

    def _run_claude_sync(self, cmd: list[str], prompt: str, cwd: Path | None = None, env: dict | None = None) -> str:
        """claude -p を同期的に実行してstdoutを返す。プロンプトはstdinで渡す"""
        import os
        run_env = None
        if env:
            run_env = {**os.environ, **env}
        result = subprocess.run(
            cmd,
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=300,
            cwd=cwd,
            env=run_env,
        )
        if result.returncode != 0:
            stderr_text = result.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"claude -p 失敗: {stderr_text}")
        return result.stdout.decode("utf-8", errors="replace")

    async def _run_claude(self, agent_info: AgentInfo, prompt: str, session_id: str | None = None, no_sync: bool = False) -> str:
        """claude -p を非同期で実行し、stdoutを返す。cwdはエージェントのディレクトリ"""
        cmd = self._build_cmd(agent_info, session_id)
        # project/agent_manager/server/runner.py → リポジトリルート/agent/
        cwd = Path(__file__).resolve().parent.parent.parent.parent / "agent" / agent_info.agent_id
        env = {"KOBITO_NO_SYNC": "1"} if no_sync else None
        return await asyncio.to_thread(self._run_claude_sync, cmd, prompt, cwd, env)

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
        stdout = await self._run_claude(agent_info, prompt, session_id, no_sync=True)
        return self._parse_result(stdout)

    async def run_stream(
        self, agent_info: AgentInfo, messages: list[Message], session_id: str | None = None
    ) -> AsyncGenerator[str | RunResult, None]:
        """ストリーミング呼び出し。テキストチャンクをyieldし、最後にRunResultをyieldする"""
        if not messages:
            raise ValueError("メッセージリストが空です")

        prompt = messages[-1].content
        stdout = await self._run_claude(agent_info, prompt, session_id, no_sync=True)
        run_result = self._parse_result(stdout)

        chunk_size = 50
        for i in range(0, len(run_result.text), chunk_size):
            yield run_result.text[i:i + chunk_size]

        # 最後にRunResultをyieldしてsession_idを呼び出し元に伝える
        yield run_result

    # ============================================================
    # 自律思考（Phase 3）
    # ============================================================

    async def think(self, agent_info: AgentInfo, agent_dir: Path) -> ThinkResult:
        """自律思考サイクルを1回実行する。Claude Codeにファイル操作を任せる"""
        prompt = ""
        raw_response = ""
        try:
            mission = await self._ensure_mission(agent_info, agent_dir)
            task = await self._ensure_task(agent_info, agent_dir, mission)
            prompt = self._build_think_prompt(mission, task)

            stdout = await self._run_claude(agent_info, prompt, no_sync=True)
            run_result = self._parse_result(stdout)
            raw_response = run_result.text

            log_path = self._save_log(agent_dir, {
                "agent_id": agent_info.agent_id,
                "prompt": prompt,
                "response": raw_response,
                "success": True,
                "error": None,
            })

            return ThinkResult(
                agent_id=agent_info.agent_id,
                response=raw_response,
                log_path=log_path,
                success=True,
                error=None,
            )
        except Exception as e:
            log_path = self._save_log(agent_dir, {
                "agent_id": agent_info.agent_id,
                "prompt": prompt,
                "response": raw_response,
                "success": False,
                "error": str(e),
            })
            return ThinkResult(
                agent_id=agent_info.agent_id,
                response=raw_response,
                log_path=log_path,
                success=False,
                error=str(e),
            )

    async def _ensure_mission(self, agent_info: AgentInfo, agent_dir: Path) -> str:
        """mission.md を読む。なければ生成して保存する。内容を返す"""
        if agent_info.mission:
            return agent_info.mission

        # LLMで生成
        prompt = (
            f"以下のシステムプロンプトに基づいて、このエージェントの目的・方針・継続的な責務を"
            f"mission.md として書いてください。Markdown形式で簡潔に。\n\n{agent_info.system_prompt}"
        )
        stdout = await self._run_claude(agent_info, prompt, no_sync=True)
        result = self._parse_result(stdout)
        mission = result.text

        (agent_dir / "mission.md").write_text(mission, encoding="utf-8")
        return mission

    async def _ensure_task(self, agent_info: AgentInfo, agent_dir: Path, mission: str) -> str:
        """task.md を読む。なければ生成して保存する。内容を返す"""
        if agent_info.task:
            return agent_info.task

        # LLMで生成
        prompt = (
            f"以下のミッションから、今やるべき具体的な作業リストを task.md として書いてください。"
            f"チェックリスト形式（- [ ] タスク）で。\n\n{mission}"
        )
        stdout = await self._run_claude(agent_info, prompt, no_sync=True)
        result = self._parse_result(stdout)
        task = result.text

        (agent_dir / "task.md").write_text(task, encoding="utf-8")
        return task

    def _build_think_prompt(self, mission: str, task: str) -> str:
        """自律思考用のプロンプトを組み立てる"""
        return (
            f"あなたの現在のミッション:\n---\n{mission}\n---\n\n"
            f"あなたの現在のタスクリスト:\n---\n{task}\n---\n\n"
            "上記のタスクリストから、今やるべきことを1つ選んで実行してください。\n\n"
            "ルール:\n"
            "- 1回の実行で2-3分で終わる範囲に絞ること\n"
            "- 大きなタスクは小さなステップに分解し、1ステップだけ進めること\n"
            "- task.md を自分で更新すること（完了タスクにチェック、新規タスク追加）\n"
            "- 成果物があれば output/ に .md ファイルとして保存し、output/index.md を更新すること\n"
            "- 最後に、何をやったか簡潔に報告すること"
        )

    def _save_log(self, agent_dir: Path, log_data: dict) -> str:
        """思考ログを保存し、ファイルパスを返す"""
        log_dir = agent_dir / "log"
        log_dir.mkdir(exist_ok=True)

        now = datetime.now(timezone.utc)
        filename = now.strftime("%Y%m%d_%H%M%S") + ".json"
        log_data["timestamp"] = now.isoformat()

        log_path = log_dir / filename
        log_path.write_text(json.dumps(log_data, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(log_path)
