"""Web 路由：下诏/召见/国势接口（SSE 流式）。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from src.core.world_state import WorldState
from src.core.turn_orchestrator import TurnOrchestrator
from src.core.historian import Historian
from src.finance.economy import FinanceState
from src.events.event_engine import EventEngine
from src.llm.provider import get_provider

router = APIRouter()
templates = Jinja2Templates(directory="src/web/templates")

# 全局状态（MVP 简化：单例）
state = WorldState()
finance = FinanceState()
orchestrator = TurnOrchestrator()
historian = Historian()
event_engine = EventEngine(Path("events/historical_events.yaml"))
provider = get_provider("mock", "mock")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """主界面。"""
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "era": state.era_label(),
            "values": state.snapshot(),
            "events": state.active_events,
            "treasury": finance.treasury,
            "inner_purse": finance.inner_purse,
        },
    )


@router.get("/state")
async def get_state():
    """国势数据（SSE 流式）。"""
    return {
        "era": state.era_label(),
        "values": state.snapshot(),
        "treasury": finance.treasury,
        "inner_purse": finance.inner_purse,
        "active_events": state.active_events,
        "resolved_events": state.resolved_events,
    }


@router.post("/edict")
async def post_edict(edict: str):
    """下诏：编排解析 → agent 执行 → 史官推演 → 落库。"""
    # 1. 编排解析
    plan = orchestrator.parse_edict(edict)

    # 2. 皇权处置/财政划拨直接处理
    if plan.type == "execute":
        return {"result": f"已赐死 {plan.target_agent}", "plan": plan.type}
    if plan.type == "dismiss":
        return {"result": f"已免职 {plan.target_agent}", "plan": plan.type}
    if plan.type == "finance_transfer" and plan.amount > 0:
        ok = finance.transfer_inner_to_treasury(plan.amount)
        return {"result": f"内帑→国库 {plan.amount} 两", "ok": ok}
    if plan.type == "finance_transfer" and plan.amount == 0:
        return {"result": "公帑不可入私库（拒绝）", "plan": "rejected"}
    if plan.type == "zonglu_reform":
        finance.apply_zonglu_reform(plan.reform_params)
        return {"result": "宗禄改革已施行", "params": plan.reform_params}

    # 3. 普通政令：mock agent 执行 + 史官推演
    agent_outputs = [
        {
            "agent_id": plan.target_agent,
            "public": f"臣领旨：{plan.task}",
            "private": f"此令或有益于国",
            "want_audience": False,
            "audience_topic": "",
        }
    ]

    # 4. 史官推演
    upcoming = event_engine.events_in_premonition(state)
    h_out = historian.run(
        state, agent_outputs, edict, upcoming, finance
    )

    # 5. delta 校验落库
    applied, errors = state.validate_delta(h_out.delta)
    state.apply(applied)

    # 6. 事件判定
    resolved, _ = event_engine.check_resolutions(state)
    event_engine.apply_fail_consequences(state)

    # 7. 时间推进
    state.advance("month")

    return {
        "plan": plan.type,
        "narrative": h_out.narrative,
        "delta": applied,
        "errors": errors,
        "resolved_events": resolved,
        "state": state.snapshot(),
    }


@router.post("/audience/{agent_id}")
async def handle_audience(agent_id: str, action: str = "grant"):
    """处理求见（见/不见）。"""
    if action == "grant":
        return {
            "result": f"召见 {agent_id}",
            "message": f"{agent_id} 奏曰：臣有本奏...",
        }
    return {"result": f"不见 {agent_id}", "consequence": "忠诚-1"}


@router.post("/advance")
async def advance_turn():
    """推进一回合。"""
    # 触发到期事件
    event_engine.trigger_events(state)
    # 财政结算
    settlement = finance.settle()
    state.apply(settlement["delta"])
    # 事件判定
    event_engine.check_resolutions(state)
    event_engine.apply_fail_consequences(state)
    # 时间推进
    state.advance("month")
    return {
        "era": state.era_label(),
        "settlement": settlement,
        "state": state.snapshot(),
    }
