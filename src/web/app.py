"""FastAPI 入口：加载配置与 GameEngine，挂载路由，提供 Web 应用。

启动：uv run uvicorn src.web.app:app --reload
默认 default_provider=mock（config.yaml），离线可跑；配置真实 Key 后切换 deepseek/claude 等。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from src.core.game_engine import GameEngine
from src.llm.provider import get_llm_for, load_config

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def create_engine(config_path: str = "config.yaml") -> GameEngine:
    """从 config 创建 GameEngine，按 config.llm 路由各 provider（默认 mock）。"""
    cfg = load_config(config_path)
    return GameEngine(
        cfg,
        orchestrator_llm=get_llm_for("orchestrator", cfg),
        historian_llm=get_llm_for("historian", cfg),
        role_llm=get_llm_for("role_agent", cfg),
    )


app = FastAPI(title="崇祯多Agent社会模拟", version="0.1.0")
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
engine: GameEngine = create_engine()

# 挂载路由
from src.web import routes  # noqa: E402

routes.register(app, engine, templates)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "era": engine.state.era_label()}
