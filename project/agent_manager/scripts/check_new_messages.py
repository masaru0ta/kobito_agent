"""UserPromptSubmitフック — chat_historyにWeb UIからのメッセージがあれば出力する"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def resolve_agent_id(cwd: str, project_root: Path) -> str | None:
    """cwdからagent_idを特定する"""
    try:
        rel = Path(cwd).relative_to(project_root)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) >= 2 and parts[0] == "agent":
        return parts[1]
    return None


# CLIで最後に確認済みのchat_historyメッセージ数を記録するファイル
def _last_seen_path(project_root: Path, agent_id: str) -> Path:
    return project_root / "agent" / agent_id / "chat_history" / ".last_seen_cli"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        hook_input = json.loads(raw)

        project_root = Path(__file__).resolve().parent.parent.parent.parent
        cwd = hook_input.get("cwd", "")
        session_id = hook_input.get("session_id", "")

        agent_id = resolve_agent_id(cwd, project_root)
        if not agent_id:
            return

        # chat_historyからsession_idが一致する会話を探す
        chat_dir = project_root / "agent" / agent_id / "chat_history"
        if not chat_dir.exists():
            return

        conv_data = None
        for path in chat_dir.glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("session_id") == session_id:
                conv_data = data
                break

        if not conv_data:
            return

        chat_messages = conv_data.get("messages", [])
        if not chat_messages:
            return

        # 最後に確認した位置を読み込む
        last_seen_file = _last_seen_path(project_root, agent_id)
        last_seen = 0
        if last_seen_file.exists():
            try:
                last_seen = int(last_seen_file.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                pass

        # last_seen以降のメッセージからsource=webのものを探す
        new_web_messages = []
        for msg in chat_messages[last_seen:]:
            if msg.get("source") == "web":
                new_web_messages.append(msg)

        # 確認済み位置を更新
        last_seen_file.write_text(str(len(chat_messages)), encoding="utf-8")

        if not new_web_messages:
            return

        print("[Web UIでの新しいやりとり]")
        for msg in new_web_messages:
            role = "ユーザー" if msg["role"] == "user" else "エージェント"
            print(f"{role}: {msg['content']}")
    except Exception:
        pass


if __name__ == "__main__":
    main()
