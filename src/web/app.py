"""FastAPI 应用入口 + SSE 流式路由。"""
from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path
from typing import AsyncGenerator

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from jinja2 import FileSystemLoader

from src.core.world_state import WorldState, DEFAULT_BOUNDS
from src.events.event_engine import EventEngine
from src.finance.economy import FinanceState

# ---- 加载配置 ----
BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "config.yaml"
EVENTS_PATH = BASE_DIR / "events" / "historical_events.yaml"

config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
bounds = config.get("bounds", DEFAULT_BOUNDS)
turn_length = config.get("game", {}).get("turn_length", "month")
difficulty = config.get("game", {}).get("difficulty", "normal")

# ---- 初始化状态 ----
state = WorldState()
finance = FinanceState()
event_engine = EventEngine(EVENTS_PATH)

# 触发开局事件
event_engine.trigger_events(state)

app = FastAPI(title="崇祯模拟器")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """主界面：早朝/对话/国势面板。"""
    era = state.era_label()
    pre = event_engine.events_in_premonition(state)
    premonitions = [e["name"] for e in pre]
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="zh">
<head><meta charset="utf-8"><title>崇祯模拟器</title>
<style>
body {{ font-family: system-ui; max-width: 800px; margin: auto; padding: 1em; background: #1a1a1a; color: #e0dcc0; }}
.panel {{ background: #2a2a2a; border: 1px solid #4a4a3a; border-radius: 8px; padding: 1em; margin: 0.5em 0; }}
.stats {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 0.5em; }}
.stat {{ background: #333; padding: 0.3em 0.6em; border-radius: 4px; text-align: center; }}
.stat-num {{ font-size: 1.2em; font-weight: bold; color: #ffd700; }}
.entry {{ background: #3a3a2a; border-left: 3px solid #ffd700; padding: 0.5em; margin: 0.3em 0; }}
pre {{ white-space: pre-wrap; }}
a {{ color: #ffd700; }}
input[type=text] {{ width: 100%; padding: 0.5em; background: #333; color: #e0dcc0; border: 1px solid #555; border-radius: 4px; }}
button {{ background: #ffd700; color: #1a1a1a; padding: 0.5em 1em; border: none; border-radius: 4px; cursor: pointer; }}
button:hover {{ background: #e6c000; }}
#log {{ max-height: 400px; overflow-y: auto; }}
</style></head>
<body>
<h2>崇祯模拟器 - {era}</h2>
<div class="panel" id="state-panel" hx-get="/state" hx-trigger="every 30s" hx-swap="innerHTML">
  <div class="stats">
    <div class="stat"><div>国库</div><div class="stat-num">{state.get("国库"):,}</div></div>
    <div class="stat"><div>内帑</div><div class="stat-num">{state.get("内帑"):,}</div></div>
    <div class="stat"><div>民心</div><div class="stat-num">{state.get("民心")}</div></div>
    <div class="stat"><div>军力</div><div class="stat-num">{state.get("军力")}</div></div>
    <div class="stat"><div>军心</div><div class="stat-num">{state.get("军心")}</div></div>
    <div class="stat"><div>陕西民心</div><div class="stat-num">{state.get("陕西_民心")}</div></div>
    <div class="stat"><div>京畿民心</div><div class="stat-num">{state.get("京畿_民心")}</div></div>
    <div class="stat"><div>朝堂清洗度</div><div class="stat-num">{state.get("朝堂清洗度")}</div></div>
  </div>
  <div style="margin-top: 0.5em; font-size: 0.9em;">
    <strong>活跃事件：</strong>{', '.join(state.active_events) if state.active_events else '无'}<br>
    <strong>预兆：</strong>{'; '.join(premonitions) if premonitions else '无'}
  </div>
</div>

<div class="panel">
  <h3>下诏</h3>
  <form hx-post="/edict" hx-trigger="submit" hx-target="#log" hx-swap="beforeend"
        _="on htmx:afterRequest reset() me">
    <input type="text" name="edict" placeholder="输入诏书（如：拨银十万赈陕西）" required>
    <button type="submit">下诏</button>
  </form>
</div>

<div class="panel">
  <h3>朝堂记录</h3>
  <div id="log">
    <div class="entry">崇祯元年正月，新帝登基，万象更新。百官列朝，待陛下旨意。</div>
  </div>
</div>
</body></html>""")


@app.get("/state", response_class=HTMLResponse)
async def get_state():
    """国势面板（HTMX 局部刷新用）。"""
    pre = event_engine.events_in_premonition(state)
    premonitions = [e["name"] for e in pre]
    return f"""
<div class="stats">
  <div class="stat"><div>国库</div><div class="stat-num">{state.get("国库"):,}</div></div>
  <div class="stat"><div>内帑</div><div class="stat-num">{state.get("内帑"):,}</div></div>
  <div class="stat"><div>民心</div><div class="stat-num">{state.get("民心")}</div></div>
  <div class="stat"><div>军力</div><div class="stat-num">{state.get("军力")}</div></div>
  <div class="stat"><div>军心</div><div class="stat-num">{state.get("军心")}</div></div>
</div>
<div style="margin-top:0.5em;font-size:0.9em;">
  <strong>活跃事件：</strong>{', '.join(state.active_events) if state.active_events else '无'}<br>
  <strong>预兆：</strong>{'; '.join(premonitions) if premonitions else '无'}
</div>"""


def _mock_turn(edict: str) -> dict:
    """mock 回合推演（单次下诏处理，验证核心闭环）。"""
    # 财政结算
    fin = finance.settle("平")
    # 编排 mock 分派
    dispatch = {"targets": ["minister_finance"], "action": "task"}
    # 史官 mock delta
    delta = {"国库": -100_000, "陕西_民心": 5}
    applied, errs = state.validate_delta(delta, bounds)
    state.apply(applied)
    # 推进时间
    state.advance(turn_length)
    # 检查事件
    event_engine.trigger_events(state)
    resolved, still = event_engine.check_resolutions(state)
    if resolved:
        for eid in resolved:
            state.resolved_events.append(eid)
    # 财政落库
    fin_result = finance.settle("平")
    state.apply({"国库": fin_result["delta"]["国库"]})
    return {
        "narrative": f"诏书「{edict[:20]}」已下，户部执行。国库-100,000，陕西民心+5。",
        "delta": delta,
        "resolved_events": resolved,
        "finance": fin_result,
        "era": state.era_label(),
    }


@app.post("/edict")
async def post_edict(request: Request):
    """下诏（流式返回叙事）。"""
    form = await request.form()
    edict = form.get("edict", "")

    async def generate() -> AsyncGenerator[str, None]:
        result = _mock_turn(edict)
        html = f"""<div class="entry">
<strong>{result['era']}</strong> 诏：{edict}<br>
{result['narrative']}
</div>"""
        for i in range(0, len(html), 3):
            yield html[i : i + 3]
            await asyncio.sleep(0.01)

    return StreamingResponse(generate(), media_type="text/html")


@app.on_event("startup")
async def startup():
    """启动时触发开局事件。"""
    event_engine.trigger_events(state)
