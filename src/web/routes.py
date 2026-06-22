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
from src.recruitment.exam import ExamSystem, exam_display, get_positions_for_rank
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
        # 科举状态：是否科举年 + 是否有未授官贡士
        year = engine.state.current_year_month()[0]
        exam_sys = ExamSystem(engine.config)
        snap["exam_available"] = exam_sys.is_exam_year(year)
        snap["exam_pending"] = bool(getattr(engine, "_exam_gongshi", None))
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

    @app.post("/dialogue/{agent_id}")
    async def dialogue(agent_id: str, message: str = Form(...)) -> JSONResponse:
        """与官员一对一对话：记录对话历史，注入摘要。"""
        inst = engine.roster.get(agent_id)
        if inst is None:
            return JSONResponse({"ok": False, "error": "该官员不在朝"}, status_code=404)
        era = engine.state.era_label()
        current_turn = engine.state.current_month_index()

        # 记录玩家消息
        inst.dialogue_memory.add_exchange("player", message, current_turn)

        # 注入对话摘要到 agent
        summary = inst.dialogue_memory.compressed_summary
        inst.agent.set_dialogue_summary(summary)

        scene = f"皇帝召见你，在御书房密谈。当前时间：{era}。"
        out = await inst.agent.respond(scene, message)

        # 记录 agent 回复
        inst.dialogue_memory.add_exchange("agent", out.public, current_turn)

        return JSONResponse({
            "ok": True,
            "agent_id": agent_id,
            "agent_name": inst.agent.name,
            "public": out.public,
            "private": out.private,
            "want_audience": out.want_audience,
        })

    @app.post("/next_turn")
    async def next_turn(edict: str = Form("")) -> StreamingResponse:
        """下一回合：启动早朝第1轮，返回百官发言。诏书暂存，等早朝结束后执行。"""
        edict_text = edict.strip() if edict.strip() else ""
        # 暂存诏书，早朝结束后执行
        engine._pending_edict = edict_text
        court_speeches: list[dict] = []
        try:
            court_speeches = await engine.start_court_phase()
        except Exception:
            pass  # 早朝失败则跳过

        async def event_stream():
            if court_speeches:
                yield _sse("court_round", {
                    "speeches": court_speeches,
                    "round": 1,
                    "can_interject": engine.get_court_session_active(),
                })
            else:
                # 无早朝（无官员），直接执行诏书
                yield _sse("court_skip", {"reason": "无官员在朝"})
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/court/interject")
    async def court_interject(message: str = Form(...)) -> JSONResponse:
        """玩家在早朝中插话（皇帝发言），百官回应。"""
        if not engine.get_court_session_active():
            return JSONResponse({"ok": False, "error": "早朝已结束"}, status_code=400)
        round_speeches, still_active = await engine.interject_court(message)
        return JSONResponse({
            "ok": True,
            "speeches": round_speeches,
            "can_interject": still_active,
        })

    @app.post("/court/end")
    async def court_end() -> StreamingResponse:
        """结束早朝，执行诏书 + 史官推演 + 结算。"""
        edict_text = getattr(engine, "_pending_edict", "") or "（本回合无诏书，朝政如常）"
        summary = await engine.finish_turn(edict_text)

        async def event_stream():
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

    @app.post("/edict")
    async def edict(edict: str = Form(...)) -> StreamingResponse:
        """下诏 → 执行一回合 → SSE 流式返回各段结果。（兼容旧接口）"""
        summary = await engine.run_turn(edict)

        async def event_stream():
            # 分段 yield，模拟流式体验
            if summary.court_speeches:
                yield _sse("court_speeches", summary.court_speeches)
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
                "court_speeches": summary.court_speeches,
            }
        )

    @app.post("/save")
    async def save_game(slot: int = Form(1)) -> JSONResponse:
        """存档到指定槽位（1/2/3）。"""
        try:
            path = engine.save_to_slot(slot)
            return JSONResponse({"ok": True, "path": path, "slot": slot})
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    @app.post("/load")
    async def load_game(slot: int = Form(1)) -> JSONResponse:
        """从指定槽位读档。"""
        try:
            engine.load_from_slot(slot)
            return JSONResponse({"ok": True, "era": engine.state.era_label(), "slot": slot})
        except FileNotFoundError:
            return JSONResponse({"ok": False, "error": f"槽位 {slot} 无存档"}, status_code=404)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    @app.post("/new_game")
    async def new_game() -> JSONResponse:
        """新游戏：重置引擎到初始状态。"""
        engine.new_game()
        return JSONResponse({
            "ok": True,
            "era": engine.state.era_label(),
        })

    @app.get("/saves")
    async def list_saves() -> JSONResponse:
        """列出所有存档槽位。"""
        return JSONResponse({"slots": GameEngine.list_saves()})

    # ---- 科举系统 ----
    @app.post("/exam/start")
    async def exam_start() -> JSONResponse:
        """开始科举：乡试→会试→生成贡士列表。仅科举年可用。"""
        year = engine.state.current_year_month()[0]
        exam = ExamSystem(engine.config)
        if not exam.is_exam_year(year):
            return JSONResponse({"ok": False, "error": f"崇祯{year}年非科举年"}, status_code=400)
        juren = exam.xiangshi(year)
        gongshi = exam.huishi(juren)
        # 存储贡士到 engine 供殿试用，并生成名次映射
        engine._exam_gongshi = gongshi
        engine._exam_year = year
        engine._exam_rankings = {c.id: i + 1 for i, c in enumerate(gongshi)}
        difficulty = engine.config.get("game", {}).get("difficulty", "normal")
        return JSONResponse({
            "ok": True,
            "year": year,
            "candidates": [exam_display(c, difficulty) for c in gongshi],
            "rankings": engine._exam_rankings,
        })

    @app.get("/exam/status")
    async def exam_status() -> JSONResponse:
        """查询科举状态：是否有待授官贡士 + 剩余贡士列表。"""
        gongshi = getattr(engine, "_exam_gongshi", None)
        if not gongshi:
            return JSONResponse({"ok": True, "pending": False, "candidates": []})
        rankings = getattr(engine, "_exam_rankings", {})
        difficulty = engine.config.get("game", {}).get("difficulty", "normal")
        candidates = []
        for c in gongshi:
            rank = rankings.get(c.id, 0)
            info = exam_display(c, difficulty)
            info["rank"] = rank
            info["positions"] = get_positions_for_rank(rank)
            candidates.append(info)
        return JSONResponse({
            "ok": True,
            "pending": True,
            "year": getattr(engine, "_exam_year", 0),
            "candidates": candidates,
        })

    @app.post("/exam/appoint_one")
    async def exam_appoint_one(
        candidate_id: str = Form(...), position_id: str = Form(...)
    ) -> JSONResponse:
        """单人授官：为一个贡士选择职位并授官。授官后从科举列表中移除。"""
        gongshi = getattr(engine, "_exam_gongshi", None)
        if not gongshi:
            return JSONResponse({"ok": False, "error": "尚未开始科举"}, status_code=400)
        rankings = getattr(engine, "_exam_rankings", {})
        year = getattr(engine, "_exam_year", 1)
        era = engine.state.era_label()
        exam = ExamSystem(engine.config)
        try:
            agent, pos_name = exam.appoint_one(
                candidate_id, position_id, gongshi, rankings,
                engine.roster, engine.role_llm, year, era,
            )
            # 从贡士列表中移除
            engine._exam_gongshi = [c for c in gongshi if c.id != candidate_id]
            if candidate_id in rankings:
                del rankings[candidate_id]
            # 如果全部授官完毕，清除科举状态
            if not engine._exam_gongshi:
                engine._exam_gongshi = None
                engine._exam_rankings = {}
            return JSONResponse({
                "ok": True,
                "name": agent.name,
                "id": agent.id,
                "position": pos_name,
                "remaining": len(engine._exam_gongshi) if engine._exam_gongshi else 0,
            })
        except (KeyError, ValueError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    @app.post("/exam/dismiss")
    async def exam_dismiss(candidate_id: str = Form(...)) -> JSONResponse:
        """放弃某个贡士（不授官，直接移除）。"""
        gongshi = getattr(engine, "_exam_gongshi", None)
        if not gongshi:
            return JSONResponse({"ok": False, "error": "尚未开始科举"}, status_code=400)
        rankings = getattr(engine, "_exam_rankings", {})
        engine._exam_gongshi = [c for c in gongshi if c.id != candidate_id]
        if candidate_id in rankings:
            del rankings[candidate_id]
        if not engine._exam_gongshi:
            engine._exam_gongshi = None
            engine._exam_rankings = {}
        return JSONResponse({"ok": True, "remaining": len(engine._exam_gongshi) if engine._exam_gongshi else 0})

    @app.post("/exam/appoint")
    async def exam_appoint(ranking: str = Form("")) -> JSONResponse:
        """殿试授官：玩家定名次，授官为 agent。（批量版，兼容旧接口）"""
        gongshi = getattr(engine, "_exam_gongshi", None)
        if not gongshi:
            return JSONResponse({"ok": False, "error": "尚未开始科举"}, status_code=400)
        exam = ExamSystem(engine.config)
        rank_list = [x.strip() for x in ranking.split(",") if x.strip()] if ranking else None
        ranked = exam.dianshi(gongshi, rank_list)
        year = getattr(engine, "_exam_year", 1)
        era = engine.state.era_label()
        new_agents = exam.appoint(ranked, engine.roster, engine.role_llm, year, era)
        engine._exam_gongshi = None
        return JSONResponse({
            "ok": True,
            "appointed": [{"name": a.name, "id": a.id} for a in new_agents],
        })


def _sse(event_type: str, data) -> str:
    return f"data: {json.dumps({'type': event_type, 'data': data}, ensure_ascii=False)}\n\n"
