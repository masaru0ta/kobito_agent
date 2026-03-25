"""configコンポーネント — エージェント定義の読み込み・バリデーション"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class AgentConfig(BaseModel):
    name: str
    model: str
    description: str = ""


class AgentInfo(BaseModel):
    agent_id: str
    config: AgentConfig
    system_prompt: str
    mission: str | None
    task: str | None


class AgentNotFoundError(Exception):
    pass


def _read_optional(path: Path) -> str | None:
    """ファイルが存在すれば内容を返し、なければNoneを返す"""
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


class ConfigManager:
    def __init__(self, agents_dir: Path):
        self._agents_dir = Path(agents_dir)

    def _ensure_agent_dir(self, agent_id: str) -> Path:
        """エージェントディレクトリを返す。存在しなければ AgentNotFoundError"""
        agent_dir = self._agents_dir / agent_id
        if not agent_dir.is_dir() or not (agent_dir / "config.yaml").exists():
            raise AgentNotFoundError(f"エージェント '{agent_id}' が見つかりません")
        return agent_dir

    def update_config(self, agent_id: str, name: str, model: str, description: str) -> AgentConfig:
        """config.yaml を更新する。未知フィールドを保持してマージする。更新後の AgentConfig を返す"""
        if not name:
            raise ValueError("名前は必須です")
        if not model:
            raise ValueError("モデルは必須です")

        agent_dir = self._ensure_agent_dir(agent_id)
        config_path = agent_dir / "config.yaml"

        # 既存の内容を読み込み（未知フィールドを保持するため）
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))

        # 更新
        raw["name"] = name
        raw["model"] = model
        raw["description"] = description

        # 書き戻し
        config_path.write_text(yaml.dump(raw, allow_unicode=True), encoding="utf-8")

        return AgentConfig(name=name, model=model, description=description)

    def update_system_prompt(self, agent_id: str, content: str) -> None:
        """CLAUDE.md を更新する。存在しなければ新規作成する"""
        agent_dir = self._ensure_agent_dir(agent_id)
        (agent_dir / "CLAUDE.md").write_text(content, encoding="utf-8")

    def list_agents(self) -> list[AgentInfo]:
        """全エージェントの情報を返す。毎回ファイルを読み直す"""
        if not self._agents_dir.exists():
            return []

        agents = []
        for d in sorted(self._agents_dir.iterdir()):
            if d.is_dir() and (d / "config.yaml").exists():
                agents.append(self._load_agent(d.name, d))
        return agents

    def get_agent(self, agent_id: str) -> AgentInfo:
        """指定エージェントの情報を返す"""
        agent_dir = self._agents_dir / agent_id
        if not agent_dir.is_dir() or not (agent_dir / "config.yaml").exists():
            raise AgentNotFoundError(f"エージェント '{agent_id}' が見つかりません")
        return self._load_agent(agent_id, agent_dir)

    def _load_agent(self, agent_id: str, agent_dir: Path) -> AgentInfo:
        """ディレクトリからエージェント情報を読み込む"""
        raw = yaml.safe_load((agent_dir / "config.yaml").read_text(encoding="utf-8"))
        config = AgentConfig(**raw)

        system_prompt = _read_optional(agent_dir / "CLAUDE.md")
        mission = _read_optional(agent_dir / "mission.md")
        task = _read_optional(agent_dir / "task.md")

        return AgentInfo(
            agent_id=agent_id,
            config=config,
            system_prompt=system_prompt or "",
            mission=mission,
            task=task,
        )
