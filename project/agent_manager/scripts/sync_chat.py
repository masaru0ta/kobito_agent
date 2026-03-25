"""CLI会話同期 — Claude CodeのStopフックで会話履歴をchat_history/に保存する"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


def resolve_agent_id(cwd: str, project_root: Path) -> str | None:
    """cwdからagent_idを特定する。agents/{name}/配下ならname、それ以外はNone"""
    try:
        rel = Path(cwd).relative_to(project_root)
    except ValueError:
        return None

    parts = rel.parts
    if len(parts) >= 2 and parts[0] == "agent":
        return parts[1]
    return None


def _chat_dir(project_root: Path, agent_id: str | None) -> Path:
    """会話履歴の保存先ディレクトリを返す"""
    if agent_id:
        d = project_root / "agent" / agent_id / "chat_history"
    else:
        d = project_root / "chat_history"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _find_conversation_by_session(chat_dir: Path, session_id: str) -> Path | None:
    """session_idが一致する会話ファイルを探す"""
    for path in chat_dir.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("session_id") == session_id:
            return path
    return None


def _parse_transcript(transcript_path: str) -> list[dict]:
    """transcript JSONLからユーザーとアシスタントのメッセージを抽出する"""
    messages = []
    path = Path(transcript_path)
    if not path.exists():
        return messages

    for line in path.read_text(encoding="utf-8").strip().split("\n"):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg = data.get("message")
        if not msg:
            continue

        role = msg.get("role")
        if role == "user":
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                # CLIコマンド関連のメッセージを除外
                if content.startswith("<local-command") or content.startswith("<command-name>"):
                    continue
                messages.append({"role": "user", "content": content})
        elif role == "assistant":
            content = msg.get("content", "")
            if isinstance(content, list):
                # content は [{"type": "text", "text": "..."}] 形式
                text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                text = "".join(text_parts)
                if text:
                    messages.append({"role": "assistant", "content": text})
            elif isinstance(content, str) and content:
                messages.append({"role": "assistant", "content": content})

    return messages


def sync_chat(hook_input: dict, project_root: Path) -> None:
    """Stopフックのデータを受け取り、会話履歴を更新する"""
    session_id = hook_input["session_id"]
    cwd = hook_input["cwd"]
    transcript_path = hook_input["transcript_path"]

    agent_id = resolve_agent_id(cwd, project_root)
    chat_dir = _chat_dir(project_root, agent_id)

    # transcriptから全メッセージを取得
    transcript_messages = _parse_transcript(transcript_path)

    # Stopフック発火時点ではassistant応答がtranscriptに未書き込みの場合がある
    # last_assistant_messageで補完する
    last_assistant = hook_input.get("last_assistant_message", "")
    if last_assistant:
        # transcriptの最後がuserで、assistantが欠けている場合に追加
        if transcript_messages and transcript_messages[-1]["role"] == "user":
            transcript_messages.append({"role": "assistant", "content": last_assistant})
        elif not transcript_messages:
            # transcriptが空でもlast_assistant_messageがあれば何もしない
            pass

    if not transcript_messages:
        return

    # session_idで既存会話を検索
    conv_path = _find_conversation_by_session(chat_dir, session_id)
    now = datetime.now(timezone.utc).isoformat()

    if conv_path:
        # 既存会話に追記
        conv_data = json.loads(conv_path.read_text(encoding="utf-8"))
        existing_count = len(conv_data["messages"])
        new_messages = transcript_messages[existing_count:]
        if not new_messages:
            return  # 差分なし
        for msg in new_messages:
            conv_data["messages"].append({
                "role": msg["role"],
                "content": msg["content"],
                "timestamp": now,
                "source": msg.get("source", "cli"),
            })
        conv_data["updated_at"] = now
    else:
        # 新規会話を作成
        conversation_id = str(uuid.uuid4())
        conv_data = {
            "conversation_id": conversation_id,
            "agent_id": agent_id,
            "created_at": now,
            "updated_at": now,
            "session_id": session_id,
            "messages": [],
        }
        for msg in transcript_messages:
            conv_data["messages"].append({
                "role": msg["role"],
                "content": msg["content"],
                "timestamp": now,
                "source": msg.get("source", "cli"),
            })
        conv_path = chat_dir / f"{conversation_id}.json"

    conv_path.write_text(json.dumps(conv_data, ensure_ascii=False), encoding="utf-8")


def main():
    """Stopフックのエントリーポイント。stdinからJSONを読んで処理する"""
    import os
    if os.environ.get("KOBITO_NO_SYNC") == "1":
        return

    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        hook_input = json.loads(raw)
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        sync_chat(hook_input, project_root)
    except Exception:
        # フックはサイレントに失敗させる（会話の邪魔をしない）
        pass


if __name__ == "__main__":
    main()
