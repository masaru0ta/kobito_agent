"""runnerコンポーネント — claude -p によるLLM呼び出しエンジン"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Literal

from pydantic import BaseModel

from server.config import AgentInfo

DEFAULT_THINK_PROMPT = """\
あなたは今から「自律思考」を1回実行する。

## 手順

1. 直近10件の会話履歴の要約を読むこと
2. 要約されていない会話履歴があれば要約を行う
3. エージェント間メッセージを確認し、未読メッセージがあれば適切に応答すること
4. mission.md を読む。なければ思考停止
5. task.md を読む。なければ mission.md から今やるべき具体的な作業リストを作成する
6. タスクリストから今やるべきことを1つ選んで実行する
7. タスクが進捗したら task.md を更新する
8. 成果物は output/ に .md ファイルとして保存する

## ルール

- 大きなタスクは小さなステップに分解し、1ステップだけ進めること
- タスクが進捗したら task.md を更新すること
- エージェント間メッセージへの応答は、自分のミッションとタスクに関連する場合のみ行うこと
"""


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    source: str | None = None


@dataclass
class StreamEvent:
    """stream-json 1行から抽出した情報"""
    event_type: str  # "assistant", "result", "other"
    text: str  # assistantイベントのtext内容（累積）
    tool_uses: list[dict]  # assistantイベントのtool_use一覧
    session_id: str  # resultイベントのsession_id
    result_text: str  # resultイベントのresultテキスト


def parse_stream_event(event: dict) -> StreamEvent:
    """claude -p のstream-json 1行をパースする"""
    etype = event.get("type", "")
    text = ""
    tool_uses = []
    session_id = ""
    result_text = ""

    if etype == "assistant":
        for item in event.get("message", {}).get("content", []):
            if item.get("type") == "text":
                text = item["text"]
            elif item.get("type") == "tool_use":
                tool_uses.append(item)
    elif etype == "result":
        session_id = event.get("session_id", "")
        result_text = event.get("result", "")

    return StreamEvent(
        event_type=etype,
        text=text,
        tool_uses=tool_uses,
        session_id=session_id,
        result_text=result_text,
    )


def _describe_tool_use(tool: dict) -> str:
    """tool_useイベントから簡潔な説明文を作る"""
    name = tool.get("name", "")
    inp = tool.get("input", {})
    if "file_path" in inp:
        return f"{name}: {Path(inp['file_path']).name}"
    if "command" in inp:
        return f"{name}: {inp['command'][:80]}"
    if "pattern" in inp:
        return f"{name}: {inp['pattern']}"
    return name


@dataclass
class ChatToolUse:
    """チャット中のtool_use通知"""
    description: str


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
    def __init__(self, config_manager=None):
        """Runnerを初期化する"""
        self._config_manager = config_manager

    async def think(self, agent_id: str) -> ThinkResult:
        """指定エージェントの自律思考を1回実行する（trigger用）"""
        if not self._config_manager:
            return ThinkResult(
                agent_id=agent_id,
                response="ConfigManager not available",
                log_path=None,
                success=False,
                error="ConfigManager not initialized"
            )

        try:
            # AgentInfoを取得
            agent_info = self._config_manager.get_agent(agent_id)
            agent_dir = Path(self._config_manager._agents_dir) / agent_id

            # think_streamを実行して結果を収集
            response = ""
            log_path = None

            async for event in self.think_stream(agent_info, agent_dir):
                if event.get("type") == "result":
                    response = event.get("content", "")
                    log_path = event.get("log_path")
                    return ThinkResult(
                        agent_id=agent_id,
                        response=response,
                        log_path=log_path,
                        success=event.get("success", True),
                        error=None
                    )
                elif event.get("type") == "error":
                    return ThinkResult(
                        agent_id=agent_id,
                        response=response,
                        log_path=event.get("log_path"),
                        success=False,
                        error=event.get("content", "Unknown error")
                    )

            # 正常完了したが結果イベントがない場合
            return ThinkResult(
                agent_id=agent_id,
                response=response,
                log_path=log_path,
                success=True,
                error=None
            )

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
            return ThinkResult(
                agent_id=agent_id,
                response="",
                log_path=None,
                success=False,
                error=error_msg
            )

    @staticmethod
    def _build_prompt_with_source(message: Message) -> str:
        """sourceに応じてプロンプトに送信者情報を付加する"""
        source = message.source or ""
        if source.startswith("agent:"):
            agent_name = source.split(":", 1)[1]
            return f"AIエージェント {agent_name} からのメッセージです:\n\n{message.content}"
        return message.content

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

    def _agent_cwd(self, agent_info: AgentInfo) -> Path:
        """エージェントのディレクトリパスを返す"""
        return Path(__file__).resolve().parent.parent.parent.parent / "agent" / agent_info.agent_id

    # ============================================================
    # ストリーミング基盤（chat / think 共通）
    # ============================================================

    async def _run_claude_stream(
        self, agent_info: AgentInfo, prompt: str,
        session_id: str | None = None, no_sync: bool = False,
    ) -> AsyncGenerator[dict, None]:
        """claude -p をストリーミング実行。stdoutの各JSON行をyieldする。
        Windows互換のためsubprocess.Popen + スレッドで実装。"""
        cmd = self._build_cmd(agent_info, session_id)
        cwd = self._agent_cwd(agent_info)

        env = {**os.environ}
        if no_sync:
            env["KOBITO_NO_SYNC"] = "1"

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
        )

        proc.stdin.write(prompt.encode("utf-8"))
        proc.stdin.close()

        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        non_json_lines: list[str] = []

        def _read_stdout():
            for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    loop.call_soon_threadsafe(queue.put_nowait, data)
                except json.JSONDecodeError:
                    non_json_lines.append(line)
            proc.wait()
            loop.call_soon_threadsafe(queue.put_nowait, None)

        reader = threading.Thread(target=_read_stdout, daemon=True)
        reader.start()

        while True:
            event = await queue.get()
            if event is None:
                break
            yield event

        reader.join()

        if proc.returncode != 0:
            stderr_text = proc.stderr.read().decode("utf-8", errors="replace").strip()
            stdout_errors = "\n".join(non_json_lines)
            details = stderr_text or stdout_errors or "(出力なし)"
            raise RuntimeError(f"claude -p 失敗 (rc={proc.returncode}): {details}")

    # ============================================================
    # チャット用ストリーミング
    # ============================================================

    async def _yield_text_delta(self, text: str, prev_text: str, chunk_size: int = 30):
        """テキストの差分をチャンク分割してyieldするヘルパー"""
        if len(text) > len(prev_text):
            delta = text[len(prev_text):]
            for i in range(0, len(delta), chunk_size):
                yield delta[i:i + chunk_size]
                await asyncio.sleep(0.01)

    async def run_stream(
        self, agent_info: AgentInfo, messages: list[Message], session_id: str | None = None
    ) -> AsyncGenerator[str | ChatToolUse | RunResult, None]:
        """ストリーミング呼び出し。テキストチャンク/tool_use通知をyieldし、最後にRunResultをyieldする"""
        if not messages:
            raise ValueError("メッセージリストが空です")

        prompt = self._build_prompt_with_source(messages[-1])
        accumulated_text = ""
        result_session_id = ""
        prev_text = ""

        async for raw_event in self._run_claude_stream(agent_info, prompt, session_id, no_sync=True):
            ev = parse_stream_event(raw_event)

            if ev.event_type == "assistant":
                if ev.text:
                    async for chunk in self._yield_text_delta(ev.text, prev_text):
                        yield chunk
                    prev_text = ev.text
                    accumulated_text = ev.text
                for tool in ev.tool_uses:
                    yield ChatToolUse(description=_describe_tool_use(tool))

            elif ev.event_type == "result":
                result_session_id = ev.session_id
                result_text = ev.result_text or accumulated_text
                async for chunk in self._yield_text_delta(result_text, prev_text):
                    yield chunk
                accumulated_text = result_text

        yield RunResult(text=accumulated_text, session_id=result_session_id)

    # ============================================================
    # 思考用ストリーミング
    # ============================================================

    async def think_stream(
        self, agent_info: AgentInfo, agent_dir: Path,
        session_id: str | None = None,
    ) -> AsyncGenerator[dict, None]:
        """自律思考をストリーミング実行。進捗イベントをyieldする"""
        if session_id:
            prompt = (
                "前回の続きを1ステップだけ進めろ。\n"
                "タスクが進捗したら task.md を更新すること。"
            )
        else:
            prompt = agent_info.think_prompt or DEFAULT_THINK_PROMPT
        accumulated_text = ""
        final_report = ""
        prev_text = ""
        events_log: list[dict] = []
        result_session_id = ""

        # プロンプトをフロントに通知
        yield {"type": "prompt", "content": prompt}

        try:
            async for raw_event in self._run_claude_stream(
                agent_info, prompt, session_id=session_id, no_sync=True,
            ):
                ev = parse_stream_event(raw_event)

                if ev.event_type == "assistant":
                    if ev.text and ev.text != prev_text:
                        prev_text = ev.text
                        accumulated_text = ev.text
                        log_ev = {"type": "text", "content": ev.text}
                        events_log.append(log_ev)
                        yield log_ev
                    for tool in ev.tool_uses:
                        desc = _describe_tool_use(tool)
                        log_ev = {"type": "tool_use", "content": desc}
                        events_log.append(log_ev)
                        yield log_ev

                elif ev.event_type == "result":
                    result_session_id = ev.session_id

            # session_idをファイルに保存
            if result_session_id:
                session_file = agent_dir / ".think_session_id"
                session_file.write_text(result_session_id, encoding="utf-8")

            # 同じセッションに「まとめろ」と投げて報告を得る
            report = await self._collect_text(agent_info, result_session_id)

            log_path = self._save_log(agent_dir, {
                "agent_id": agent_info.agent_id,
                "prompt": prompt,
                "response": report,
                "events": events_log,
                "session_id": result_session_id,
                "success": True,
                "error": None,
            })
            yield {"type": "result", "content": report, "log_path": log_path, "success": True}

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
            log_path = self._save_log(agent_dir, {
                "agent_id": agent_info.agent_id,
                "prompt": prompt,
                "response": accumulated_text,
                "events": events_log,
                "session_id": result_session_id,
                "success": False,
                "error": error_msg,
            })
            yield {"type": "error", "content": error_msg, "log_path": log_path, "success": False}

    # ============================================================
    # 非ストリーミング（要約など）
    # ============================================================

    def _run_claude_sync(self, cmd: list[str], prompt: str, cwd: Path | None = None, env: dict | None = None) -> str:
        """claude -p を同期的に実行してstdoutを返す。プロンプトはstdinで渡す"""
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
        """claude -p を非同期で実行し、stdoutを返す（非ストリーミング）"""
        cmd = self._build_cmd(agent_info, session_id)
        cwd = self._agent_cwd(agent_info)
        env = {"KOBITO_NO_SYNC": "1"} if no_sync else None
        return await asyncio.to_thread(self._run_claude_sync, cmd, prompt, cwd, env)

    def _parse_result(self, stdout: str) -> RunResult:
        """stream-json出力からresultテキストとsession_idを抽出する"""
        result_text = None
        session_id = None
        accumulated_text = ""

        for line in stdout.strip().split("\n"):
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            ev = parse_stream_event(data)
            if ev.event_type == "assistant" and ev.text:
                accumulated_text = ev.text
            elif ev.event_type == "result":
                result_text = ev.result_text or accumulated_text
                session_id = ev.session_id

        if result_text is None:
            raise RuntimeError("claude -p から応答を取得できませんでした")

        return RunResult(text=result_text, session_id=session_id or "")

    async def _collect_text(self, agent_info: AgentInfo, session_id: str) -> str:
        """セッション継続でテキストのみ収集する（要約取得用）"""
        if not session_id:
            return ""
        summary_prompt = (
            "今回の作業で何をしたか、以下の形式でまとめろ。ツールは使うな。\n\n"
            "## 報告\n- （やったことを完了形で）\n\n"
            "## 変更ファイル\n- （変更したファイル名）\n\n"
            "## 次回\n- （次にやるべきこと）"
        )
        text = ""
        async for raw_event in self._run_claude_stream(
            agent_info, summary_prompt, session_id=session_id, no_sync=True,
        ):
            ev = parse_stream_event(raw_event)
            if ev.event_type == "assistant" and ev.text:
                text = ev.text
            elif ev.event_type == "result":
                text = ev.result_text or text
        return text

    async def run(self, agent_info: AgentInfo, messages: list[Message], session_id: str | None = None) -> RunResult:
        """非ストリーミング呼び出し。RunResult（テキスト+session_id）を返す"""
        if not messages:
            raise ValueError("メッセージリストが空です")

        prompt = self._build_prompt_with_source(messages[-1])
        stdout = await self._run_claude(agent_info, prompt, session_id, no_sync=True)
        return self._parse_result(stdout)

    # ============================================================
    # 要約
    # ============================================================

    async def summarize_text(self, agent_info: AgentInfo, text: str) -> dict:
        """テキストを要約してtitle/summaryを返す。会話や思考ログの要約に使う"""

        prompt = (
            "以下のテキストに対して、JSON形式で返してください。それ以外のテキストは含めないでください。\n\n"
            f"{text}\n\n"
            "titleは「テーマと結論」を30文字以内でまとめてください。\n"
            "summaryは流れと要点を100文字以内でまとめてください。\n\n"
            '{"title": "テーマと結論（30文字以内）", "summary": "要約（100文字以内）"}'
        )

        result = await self.run(
            agent_info,
            [Message(role="user", content=prompt)],
        )

        json_match = re.search(r'\{[^}]+\}', result.text)
        if json_match:
            parsed = json.loads(json_match.group())
            return {
                "title": parsed.get("title", "")[:50],
                "summary": parsed.get("summary", "")[:200],
            }
        return {"title": result.text[:50], "summary": ""}

    # ============================================================
    # ログ保存
    # ============================================================

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
