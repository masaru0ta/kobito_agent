"""configコンポーネント — エージェント定義の読み込み・バリデーション"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class TriggerConfig(BaseModel):
    cron: str
    enabled: bool = True


class AgentConfig(BaseModel):
    name: str
    model: str
    description: str = ""
    trigger: TriggerConfig | None = None


class AgentInfo(BaseModel):
    agent_id: str
    config: AgentConfig
    system_prompt: str
    mission: str | None
    task: str | None
    think_prompt: str | None = None


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

    def _read_config(self, agent_id: str) -> tuple[Path, dict]:
        """config.yamlを読み込み、(パス, 辞書)を返す"""
        agent_dir = self._ensure_agent_dir(agent_id)
        config_path = agent_dir / "config.yaml"
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        return config_path, raw

    def _write_config(self, config_path: Path, raw: dict) -> AgentConfig:
        """config.yamlを書き戻し、AgentConfigを返す"""
        config_path.write_text(yaml.dump(raw, allow_unicode=True), encoding="utf-8")
        return AgentConfig(**raw)

    def update_config(self, agent_id: str, name: str, model: str, description: str) -> AgentConfig:
        """config.yaml を更新する。未知フィールドを保持してマージする"""
        if not name:
            raise ValueError("名前は必須です")
        if not model:
            raise ValueError("モデルは必須です")

        config_path, raw = self._read_config(agent_id)
        raw["name"] = name
        raw["model"] = model
        raw["description"] = description
        return self._write_config(config_path, raw)

    def update_trigger_config(self, agent_id: str, cron: str, enabled: bool) -> AgentConfig:
        """trigger設定を更新する。未知フィールドを保持してマージする"""
        if not cron:
            raise ValueError("cron式は必須です")

        config_path, raw = self._read_config(agent_id)
        raw["trigger"] = {"cron": cron, "enabled": enabled}
        return self._write_config(config_path, raw)

    def remove_trigger_config(self, agent_id: str) -> AgentConfig:
        """trigger設定を削除する"""
        config_path, raw = self._read_config(agent_id)
        raw.pop("trigger", None)
        return self._write_config(config_path, raw)

    def save_settings(self, agent_id: str, name: str, model: str, description: str,
                      system_prompt: str, trigger_cron: str | None, trigger_enabled: bool) -> AgentConfig:
        """設定画面の全項目を一括保存する。config.yamlとCLAUDE.mdを1回で書く"""
        if not name:
            raise ValueError("名前は必須です")
        if not model:
            raise ValueError("モデルは必須です")

        config_path, raw = self._read_config(agent_id)
        raw["name"] = name
        raw["model"] = model
        raw["description"] = description

        if trigger_enabled and trigger_cron:
            raw["trigger"] = {"cron": trigger_cron, "enabled": True}
        else:
            raw.pop("trigger", None)

        result = self._write_config(config_path, raw)
        agent_dir = config_path.parent
        (agent_dir / "CLAUDE.md").write_text(system_prompt, encoding="utf-8")

        return result

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
        think_prompt = _read_optional(agent_dir / "think_prompt.md")

        return AgentInfo(
            agent_id=agent_id,
            config=config,
            system_prompt=system_prompt or "",
            mission=mission,
            task=task,
            think_prompt=think_prompt,
        )
