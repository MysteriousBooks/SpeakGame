"""Web 路由：下诏（SSE 流式）/ 召见·求见 / 国势面板 / 招募池。

设计要点（见计划第4节架构、第7节技术选型）：
- FastAPI + SSE 流式：下诏后分段 yield 回合结果（叙事→数值→事件→求见→预兆）。
- HTMX/Jinja2 极简前端：国势面板（数值/内帑国库/事件/预兆/招募池/科举）。
"""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from src.core.game_engine import GameEngine
from src.recruitment.roster import recruit_display


def register(app: FastAPI, engine: GameEngine, templates: Jinja2Templates) -> None:
    """把路由注册到 app，共享 engine 与 templates。"""

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        snap = engine.state_snapshot()
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "state": snap,
                "premonitions": engine.events.upcoming_premonitions(
                    engine.state.current_month_index()
                ),
            },
        )

    @app.get("/state")
    async def state() -> JSONResponse:
        snap = engine.state_snapshot()
        snap["premonitions"] = engine.events.upcoming_premonitions(
            engine.state.current_month_index()
        )
        return JSONResponse(snap)

    @app.get("/recruit")
    async def recruit_pool() -> JSONResponse:
        """招募池（按难度过滤可见信息）。"""
        year = engine.state.current_year_month()[0]
        available = engine.roster.available_for_recruit(year)
        difficulty = engine.config.get("game", {}).get("difficulty", "normal")
        return JSONResponse(
            {
                "difficulty": difficulty,
                "candidates": [recruit_display(p, difficulty) for p in available],
            }
        )

    @app.post("/recruit/{persona_id}")
    async def recruit_one(persona_id: str) -> JSONResponse:
        era = engine.state.era_label()
        try:
            agent = engine.roster.recruit(persona_id, engine.role_llm, era)
            return JSONResponse({"ok": True, "name": agent.name, "id": agent.id})
        except (KeyError, ValueError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    @app.post("/audience/{agent_id}")
    async def handle_audience(agent_id: str, action: str = Form(...)) -> JSONResponse:
        """处理求见：action=grant（召见）/ decline（拒见）。"""
        if action == "grant":
            engine.audience.grant(agent_id)
            return JSONResponse({"ok": True, "granted": True})
        out = engine.audience.decline(agent_id)
        inst = engine.roster.get(agent_id)
        if inst is not None:
            inst.loyalty = max(0, inst.loyalty + out.loyalty_delta)
        return JSONResponse({"ok": True, "granted": False, "loyalty_delta": out.loyalty_delta})

    @app.post("/edict")
    async def edict(edict: str = Form(...)) -> StreamingResponse:
        """下诏 → 执行一回合 → SSE 流式返回各段结果。"""
        summary = await engine.run_turn(edict)

        async def event_stream():
            # 分段 yield，模拟流式体验（真逐 token 流式在 M4/后续）
            yield _sse("narrative", summary.narrative)
            await asyncio.sleep(0)
            if summary.execution_public:
                yield _sse("execution", summary.execution_public)
            yield _sse(
                "delta",
                {"applied": summary.delta_applied, "clipped": summary.delta_clipped},
            )
            yield _sse("finance", summary.finance_settlement)
            if summary.new_events_triggered:
                yield _sse("new_events", summary.new_events_triggered)
            if summary.events_resolved:
                yield _sse("resolved", summary.events_resolved)
            if summary.fail_delta:
                yield _sse("fail", summary.fail_delta)
            if summary.audience_queue:
                yield _sse("audience", summary.audience_queue)
            if summary.premonitions:
                yield _sse("premonitions", summary.premonitions)
            if summary.task:
                yield _sse("task", summary.task)
            yield _sse("era", summary.era)
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/edict/json")
    async def edict_json(edict: str = Form(...)) -> JSONResponse:
        """非流式版下诏（便于脚本/测试）。"""
        summary = await engine.run_turn(edict)
        return JSONResponse(
            {
                "era": summary.era,
                "narrative": summary.narrative,
                "delta_applied": summary.delta_applied,
                "delta_clipped": summary.delta_clipped,
                "finance": summary.finance_settlement,
                "new_events_triggered": summary.new_events_triggered,
                "events_resolved": summary.events_resolved,
                "fail_delta": summary.fail_delta,
                "audience_queue": summary.audience_queue,
                "premonitions": summary.premonitions,
                "task": summary.task,
                "execution_public": summary.execution_public,
            }
        )

    @app.post("/save")
    async def save(path: str = Form("saves/save.json")) -> JSONResponse:
        from pathlib import Path

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        engine.save(path)
        return JSONResponse({"ok": True, "path": path})


def _sse(event_type: str, data) -> str:
    return f"data: {json.dumps({'type': event_type, 'data': data}, ensure_ascii=False)}\n\n"
