"""Webサーバー — FastAPIアプリケーション"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from server.chat import ChatManager
from server.config import ConfigManager
from server.inter_agent_session import InterAgentSessionManager
from server.runner import Runner
from server.trigger import TriggerManager
from server.routes.agents import router as agents_router
from server.routes.chat import router as chat_router
from server.routes.inter_agent import router as inter_agent_router
from server.routes.think import router as think_router
from server.routes.files import router as files_router
from server.routes.triggers import router as triggers_router


def create_app(
    agents_dir: Path | None = None,
    runner: Runner | None = None,
    config_manager: ConfigManager | None = None,
    trigger_manager: TriggerManager | None = None,
) -> FastAPI:
    if agents_dir is None:
        # server/app.py → agent_manager → project → リポジトリルート → agent/
        agents_dir = Path(__file__).resolve().parent.parent.parent.parent / "agent"
    if config_manager is None:
        config_manager = ConfigManager(agents_dir)
    if runner is None:
        runner = Runner(config_manager=config_manager)
    if trigger_manager is None:
        trigger_manager = TriggerManager(config_manager, runner, agents_dir)

    chat_manager = ChatManager(config_manager, runner, agents_dir)
    session_manager = InterAgentSessionManager(agents_dir, config_manager, runner)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await trigger_manager.start()
        yield
        await trigger_manager.stop()

    app = FastAPI(title="kobito_agent", lifespan=lifespan)

    # 共有オブジェクトをapp.stateに格納（ルーターからDepends経由でアクセス）
    app.state.config_manager = config_manager
    app.state.runner = runner
    app.state.trigger_manager = trigger_manager
    app.state.chat_manager = chat_manager
    app.state.agents_dir = agents_dir
    app.state.session_manager = session_manager

    # ルーター登録
    app.include_router(agents_router)
    app.include_router(chat_router)
    app.include_router(inter_agent_router)
    app.include_router(think_router)
    app.include_router(files_router)
    app.include_router(triggers_router)

    # 静的ファイル配信（APIルートより後にマウント）
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
