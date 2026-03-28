"""ログ・成果物API"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from server.config import AgentInfo
from server.routes.deps import (
    _get_agents_dir,
    get_agent_or_404,
    safe_path,
)

router = APIRouter(prefix="/api/agents/{agent_id}", tags=["files"])


# --- ログ ---

@router.get("/logs")
def get_logs(agent_id: str, request: Request,
             agent: AgentInfo = Depends(get_agent_or_404)):
    agents_dir = _get_agents_dir(request)
    log_dir = safe_path(agents_dir, agent_id, "log")
    if not log_dir.exists():
        return []

    logs = []
    for path in sorted(log_dir.glob("*.json"), reverse=True):
        data = json.loads(path.read_text(encoding="utf-8"))
        response = data.get("response", "")
        logs.append({
            "filename": path.name,
            "timestamp": data.get("timestamp"),
            "summary": response[:100] if response else "",
            "success": data.get("success", False),
        })
    return logs


@router.get("/logs/{filename}")
def get_log_detail(agent_id: str, filename: str, request: Request,
                   agent: AgentInfo = Depends(get_agent_or_404)):
    agents_dir = _get_agents_dir(request)
    log_path = safe_path(agents_dir, agent_id, "log", filename)
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="ログが見つかりません")
    return json.loads(log_path.read_text(encoding="utf-8"))


# --- 成果物 ---

@router.get("/outputs")
def get_outputs(agent_id: str, request: Request,
                agent: AgentInfo = Depends(get_agent_or_404)):
    agents_dir = _get_agents_dir(request)
    output_dir = safe_path(agents_dir, agent_id, "output")
    if not output_dir.exists():
        return []

    outputs = []
    for path in sorted(output_dir.glob("*.md")):
        if path.name == "index.md":
            continue
        # 先頭の # 行からタイトルを取得
        title = path.stem
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
        except Exception:
            pass
        stat = path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime("%Y-%m-%d")
        outputs.append({
            "filename": path.name,
            "title": title,
            "date": mtime,
            "size": stat.st_size,
        })
    # 日付の新しい順
    outputs.sort(key=lambda x: x["date"], reverse=True)
    return outputs


@router.get("/outputs/{filename}")
def get_output_content(agent_id: str, filename: str, request: Request,
                       agent: AgentInfo = Depends(get_agent_or_404)):
    agents_dir = _get_agents_dir(request)
    output_path = safe_path(agents_dir, agent_id, "output", filename)
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="成果物が見つかりません")
    return {
        "filename": filename,
        "content": output_path.read_text(encoding="utf-8"),
    }


# --- タスク ---

def _calculate_progress(content: str) -> tuple[int, int, int]:
    """チェックリストから進捗率を計算"""
    import re

    completed = len(re.findall(r'^\s*- \[x\]', content, re.MULTILINE | re.IGNORECASE))
    total = len(re.findall(r'^\s*- \[\s*[x\s]\s*\]', content, re.MULTILINE | re.IGNORECASE))

    progress = int((completed / total * 100)) if total > 0 else 0
    return progress, completed, total


def _extract_title(content: str, fallback: str) -> str:
    """Markdownの先頭 # 行からタイトルを取得"""
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def _extract_status(content: str) -> str:
    """本文の **ステータス: xxx** からステータスを抽出"""
    import re

    match = re.search(r'\*\*ステータス:\s*(.+?)\*\*', content)
    if not match:
        return "不明"
    return match.group(1).strip()


@router.get("/tasks")
def get_tasks(agent_id: str, request: Request,
              agent: AgentInfo = Depends(get_agent_or_404)):
    agents_dir = _get_agents_dir(request)
    tasks_dir = safe_path(agents_dir, agent_id, "tasks")
    if not tasks_dir.exists():
        return []

    tasks = []
    for path in sorted(tasks_dir.glob("*.md")):
        if path.name == "index.md":
            continue

        content = path.read_text(encoding="utf-8")
        title = _extract_title(content, path.stem)
        status = _extract_status(content)
        progress, completed, total = _calculate_progress(content)

        stat = path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime("%Y-%m-%d")

        tasks.append({
            "filename": path.name,
            "title": title,
            "status": status,
            "progress": progress,
            "completed_tasks": completed,
            "total_tasks": total,
            "date": mtime,
        })

    # 未承認を先に、その後進捗率の低い順
    status_order = {"未承認": 0, "承認済": 1, "完了": 2}
    tasks.sort(key=lambda x: (status_order.get(x["status"], 99), x["progress"]))

    return tasks


@router.get("/tasks/{filename}")
def get_task_content(agent_id: str, filename: str, request: Request,
                     agent: AgentInfo = Depends(get_agent_or_404)):
    agents_dir = _get_agents_dir(request)
    task_path = safe_path(agents_dir, agent_id, "tasks", filename)
    if not task_path.exists():
        raise HTTPException(status_code=404, detail="タスクが見つかりません")

    content = task_path.read_text(encoding="utf-8")
    progress, completed, total = _calculate_progress(content)

    return {
        "filename": filename,
        "content": content,
        "progress": progress,
        "completed_tasks": completed,
        "total_tasks": total,
    }


@router.post("/tasks/{filename}/approve")
def approve_task(agent_id: str, filename: str, request: Request,
                 agent: AgentInfo = Depends(get_agent_or_404)):
    agents_dir = _get_agents_dir(request)
    task_path = safe_path(agents_dir, agent_id, "tasks", filename)
    if not task_path.exists():
        raise HTTPException(status_code=404, detail="タスクが見つかりません")

    content = task_path.read_text(encoding="utf-8")
    import re
    new_content = re.sub(
        r'\*\*ステータス:\s*.+?\*\*',
        '**ステータス: 承認済**',
        content,
        count=1,
    )
    if new_content == content:
        raise HTTPException(status_code=400, detail="ステータス行が見つかりません")

    task_path.write_text(new_content, encoding="utf-8")
    return {"filename": filename, "status": "承認済"}
