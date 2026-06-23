# 对话诏书提取与回合流程重设计 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现从官员对话中自动提取诏书建议（含人事任免），重构回合流程为先推演后早朝

**Architecture:** 后端新增 LLM 提取方法 + 编排 agent 扩展 appoint 类型 + 两步 next_turn 路由；前端新增确认模态框 + 两步交互 + 早朝后置

**Tech Stack:** Python FastAPI, Jinja2, SSE, LLM (role_llm)

---

### Task 1: Roster 新增 find_by_name 方法

**Files:**
- Modify: `src/recruitment/roster.py` (在 get_talent_pool 方法后新增)

- [ ] **Step 1: 在 Roster 类中新增 find_by_name 方法**

在 `get_talent_pool` 方法（第132行）之后、`make_agent` 方法之前，新增：

```python
def find_by_name(self, name: str) -> AgentInstance | None:
    """按姓名查找角色实例（用于编排解析任免指令时定位目标）。"""
    for inst in self.instances.values():
        if inst.persona.name == name:
            return inst
    return None
```

- [ ] **Step 2: 验证语法正确**

Run: `python -c "from src.recruitment.roster import Roster; print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add src/recruitment/roster.py
git commit -m "feat: add find_by_name to Roster for appointment lookup"
```

---

### Task 2: 新增提取结果数据结构 + GameEngine.extract_edicts_from_dialogues

**Files:**
- Modify: `src/core/game_engine.py` (新增 dataclass + 提取方法)

- [ ] **Step 1: 在 game_engine.py 中 TurnSummary 之前新增数据结构**

在 `TurnSummary` dataclass（第31行）之前新增：

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractedSuggestion:
    """从对话中提取的一条建议。"""
    type: str  # "policy" | "appoint" | "dismiss"
    content: str  # 建议的文本内容
    source_agent_id: str
    source_agent_name: str
    # 人事任免相关
    target_person_name: str | None = None
    target_position_name: str | None = None
    reason: str = ""


@dataclass
class ExtractionResult:
    """LLM 从对话中提取的所有建议。"""
    policy_suggestions: list[ExtractedSuggestion] = field(default_factory=list)
    personnel_suggestions: list[ExtractedSuggestion] = field(default_factory=list)
```

- [ ] **Step 2: 在 GameEngine 中新增 extract_edicts_from_dialogues 方法**

在 `compress_dialogues` 方法（第482行）之前新增：

```python
EXTRACT_EDICTS_PROMPT = (
    "你是一个明朝朝廷诏书建议提取助手。分析以下皇帝与大臣的对话记录，"
    "提取出大臣提出的政策建议和人事任免建议。\n\n"
    "政策建议：大臣提出的治国方略、财政调整、军事行动、赈灾等具体施政建议。\n"
    "人事任免：大臣举荐某人担任某职位、或弹劾某人请求罢免。\n\n"
    "注意：\n"
    "- 只提取明确提出的建议，不要臆测\n"
    "- 忽略寒暄、客套话、无关话题\n"
    "- 人事任免必须包含具体的人名和职位\n\n"
    "对话记录：\n{dialogues}\n\n"
    "请以 JSON 格式输出提取结果："
)

EXTRACT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "policy_suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "source_agent_id": {"type": "string"},
                    "source_agent_name": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["content", "source_agent_id", "source_agent_name"],
            },
        },
        "personnel_suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["appoint", "dismiss"]},
                    "content": {"type": "string"},
                    "source_agent_id": {"type": "string"},
                    "source_agent_name": {"type": "string"},
                    "target_person_name": {"type": "string"},
                    "target_position_name": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["type", "content", "source_agent_id", "source_agent_name"],
            },
        },
    },
    "required": ["policy_suggestions", "personnel_suggestions"],
}

async def extract_edicts_from_dialogues(self) -> ExtractionResult:
    """扫描当前回合所有 active agent 的对话记录，用 LLM 提取诏书建议。"""
    current_turn = self.state.current_month_index()
    dialogues: list[str] = []
    for inst in self.roster.instances.values():
        if inst.status != "active":
            continue
        # 只取当前回合的对话
        turn_exchanges = [e for e in inst.dialogue_memory.exchanges if e.turn == current_turn]
        if not turn_exchanges:
            continue
        for e in turn_exchanges:
            role = "帝" if e.role == "player" else inst.persona.name
            dialogues.append(f"{role}：{e.content}")
    if not dialogues:
        return ExtractionResult()

    dialogues_text = "\n".join(dialogues)
    prompt = self.EXTRACT_EDICTS_PROMPT.format(dialogues=dialogues_text)
    try:
        out = await self.role_llm.chat_json(
            [Message("user", prompt)],
            schema=self.EXTRACT_SCHEMA,
            system="你是一个明朝朝廷诏书建议提取助手。",
            max_retries=1,
        )
    except Exception:
        return ExtractionResult()

    policy = [
        ExtractedSuggestion(
            type="policy", content=s["content"],
            source_agent_id=s["source_agent_id"],
            source_agent_name=s["source_agent_name"],
            reason=s.get("reason", ""),
        )
        for s in out.get("policy_suggestions", [])
    ]
    personnel = [
        ExtractedSuggestion(
            type=s.get("type", "appoint"), content=s["content"],
            source_agent_id=s["source_agent_id"],
            source_agent_name=s["source_agent_name"],
            target_person_name=s.get("target_person_name"),
            target_position_name=s.get("target_position_name"),
            reason=s.get("reason", ""),
        )
        for s in out.get("personnel_suggestions", [])
    ]
    return ExtractionResult(policy_suggestions=policy, personnel_suggestions=personnel)
```

- [ ] **Step 3: 验证语法正确**

Run: `python -c "from src.core.game_engine import GameEngine, ExtractedSuggestion, ExtractionResult; print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add src/core/game_engine.py
git commit -m "feat: add dialogue edict extraction with ExtractedSuggestion dataclass"
```

---

### Task 3: 编排 agent 扩展 appoint 类型

**Files:**
- Modify: `src/core/turn_orchestrator.py`

- [ ] **Step 1: 在 ORCHESTRATOR_SCHEMA 中新增 appoint action 和 appointments 字段**

修改 `ORCHESTRATOR_SCHEMA` 的 `action` enum（第31行）和 `properties`（第28行）：

```python
ORCHESTRATOR_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["execute", "dismiss", "execute_death", "finance_transfer", "court_only", "noop", "appoint"],
        },
        "dispatch_targets": {"type": "array", "items": {"type": "string"}},
        "visits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "purpose": {"type": "string"},
                },
            },
        },
        "activation_order": {"type": "array", "items": {"type": "string"}},
        "task": {
            "type": "object",
            "properties": {
                "target_agent": {"type": "string"},
                "content": {"type": "string"},
                "affects": {"type": "array", "items": {"type": "string"}},
                "deadline": {"type": "string"},
                "success_condition": {"type": "string"},
            },
        },
        "finance_action": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": [
                        "inner_to_treasury",
                        "treasury_to_inner",
                        "tax_adjust",
                        "expense_adjust",
                        "zonglu_reform",
                    ],
                },
                "amount": {"type": "number"},
                "detail": {"type": "string"},
            },
        },
        "appointments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "person_name": {"type": "string"},
                    "position_name": {"type": "string"},
                    "action": {"type": "string", "enum": ["appoint", "dismiss"]},
                },
                "required": ["person_name", "action"],
            },
        },
        "reason": {"type": "string"},
    },
    "required": ["action", "dispatch_targets"],
}
```

- [ ] **Step 2: 在 OrchestratorPlan 中新增 appointments 字段和 is_appoint 属性**

修改 `OrchestratorPlan` dataclass（第79行起）：

```python
@dataclass
class OrchestratorPlan:
    """编排解析诏书的分派/处置/财政/任免计划。"""

    action: str = "noop"
    dispatch_targets: list[str] = field(default_factory=list)
    visits: list[dict] = field(default_factory=list)
    activation_order: list[str] = field(default_factory=list)
    task: dict | None = None
    finance_action: dict | None = None
    target: str | None = None  # 处置对象（赐死/免职）
    appointments: list[dict] = field(default_factory=list)  # 任免列表
    reason: str = ""

    @property
    def is_dismiss(self) -> bool:
        return self.action == "dismiss"

    @property
    def is_execute_death(self) -> bool:
        return self.action == "execute_death"

    @property
    def is_finance_transfer(self) -> bool:
        return self.action == "finance_transfer"

    @property
    def is_appoint(self) -> bool:
        return self.action == "appoint"

    @classmethod
    def from_dict(cls, d: dict) -> "OrchestratorPlan":
        task = d.get("task")
        fin = d.get("finance_action")
        return cls(
            action=d.get("action", "noop"),
            dispatch_targets=list(d.get("dispatch_targets", [])),
            visits=list(d.get("visits", [])),
            activation_order=list(d.get("activation_order", [])),
            task=task if isinstance(task, dict) and task else None,
            finance_action=fin if isinstance(fin, dict) and fin else None,
            target=d.get("target") or (task.get("target_agent") if isinstance(task, dict) else None),
            appointments=list(d.get("appointments", [])),
            reason=d.get("reason", ""),
        )
```

- [ ] **Step 3: 验证语法正确**

Run: `python -c "from src.core.turn_orchestrator import OrchestratorPlan; p=OrchestratorPlan(action='appoint', appointments=[{'person_name':'test','action':'appoint'}]); print(p.is_appoint, p.appointments)"`
Expected: `True [{'person_name': 'test', 'action': 'appoint'}]`

- [ ] **Step 4: Commit**

```bash
git add src/core/turn_orchestrator.py
git commit -m "feat: extend orchestrator with appoint action type"
```

---

### Task 4: GameEngine 执行任免逻辑

**Files:**
- Modify: `src/core/game_engine.py` (在 _run_post_court 中新增任免执行)

- [ ] **Step 1: 在 _run_post_court 的处置/财政/任务区块后新增任免执行**

在 `_run_post_court` 方法中，第337行（`if plan.is_finance_transfer` 之后）、第339行（`if plan.task` 之前）插入：

```python
        # 2.5 执行任免（编排解析出的 appoint/dismiss）
        appointment_results: list[dict] = []
        if plan.is_appoint and plan.appointments:
            for apt in plan.appointments:
                if apt["action"] == "appoint":
                    target = self.roster.find_by_name(apt["person_name"])
                    if target is None:
                        appointment_results.append({"action": "appoint", "person": apt["person_name"], "ok": False, "error": "未找到目标"})
                        continue
                    # 查找目标职位
                    pos = self.positions.get_by_name(apt.get("position_name", ""))
                    if pos is None:
                        appointment_results.append({"action": "appoint", "person": apt["person_name"], "ok": False, "error": f"职位 {apt.get('position_name')} 不存在"})
                        continue
                    result = self.appoint_official(target.persona.id, pos.id)
                    appointment_results.append({"action": "appoint", "person": apt["person_name"], "position": pos.name, "ok": result["ok"], "error": result.get("error")})
                elif apt["action"] == "dismiss":
                    target = self.roster.find_by_name(apt["person_name"])
                    if target is None:
                        appointment_results.append({"action": "dismiss", "person": apt["person_name"], "ok": False, "error": "未找到目标"})
                        continue
                    try:
                        self.dismiss_official(target.persona.id)
                        appointment_results.append({"action": "dismiss", "person": apt["person_name"], "ok": True})
                    except ValueError as e:
                        appointment_results.append({"action": "dismiss", "person": apt["person_name"], "ok": False, "error": str(e)})
```

- [ ] **Step 2: 在 TurnSummary 中新增 appointment_results 字段**

修改 `TurnSummary`（第31行），在 `execution_public` 后新增：

```python
    execution_public: list[dict] = field(default_factory=dict)  # [{agent_id, name, public}]
    court_speeches: list[dict] = field(default_factory=list)    # 早朝发言 [{speaker_id, speaker_name, public}]
    appointment_results: list[dict] = field(default_factory=list)  # 任免执行结果
```

- [ ] **Step 3: 在 _run_post_court 的 summary 构建中传入 appointment_results**

在 `_run_post_court` 方法末尾的 `TurnSummary` 构建（第420行）中新增：

```python
        summary = TurnSummary(
            era=self.state.era_label(),
            narrative=turn_result.narrative,
            delta_applied=dict(delta_result.applied),
            delta_clipped=dict(delta_result.clipped),
            finance_settlement={...},
            new_events_triggered=[e.name for e in newly_triggered],
            events_resolved=[ae.event.name for ae in resolved],
            fail_delta=fail_delta,
            audience_queue=[r.to_dict() for r in self.audience.items()],
            premonitions=prems,
            task=plan_task_snapshot,
            execution_public=execution_public,
            court_speeches=court_speeches_data,
            appointment_results=appointment_results,
        )
```

- [ ] **Step 4: 在 turn_history 落库中新增 appointment_results**

在 `_run_post_court` 的 turn_history 构建（第440行）中新增：

```python
        self.turn_history.append(
            {
                "era": summary.era,
                "edict": edict,
                "narrative": summary.narrative,
                "execution_public": summary.execution_public,
                "delta_applied": dict(summary.delta_applied),
                "new_events_triggered": summary.new_events_triggered,
                "events_resolved": summary.events_resolved,
                "fail_delta": dict(summary.fail_delta),
                "audience_queue": list(summary.audience_queue),
                "court_speeches": list(summary.court_speeches),
                "appointment_results": list(summary.appointment_results),
            }
        )
```

- [ ] **Step 5: 验证语法正确**

Run: `python -c "from src.core.game_engine import GameEngine; print('OK')"`
Expected: OK

- [ ] **Step 6: Commit**

```bash
git add src/core/game_engine.py
git commit -m "feat: execute appointments in _run_post_court"
```

---

### Task 5: 路由层两步 next_turn + 早朝后置

**Files:**
- Modify: `src/web/routes.py`

- [ ] **Step 1: 修改 /next_turn 为两步流程**

将 `/next_turn` 路由（第119-143行）替换为：

```python
    @app.post("/next_turn")
    async def next_turn(action: str = Form("extract"), edict: str = Form("")) -> JSONResponse:
        """下一回合两步流程：
        - action=extract（第一步）：扫描对话提取建议，返回提取结果
        - action=execute（第二步）：执行推演，返回 SSE 流
        """
        if action == "extract":
            result = await engine.extract_edicts_from_dialogues()
            return JSONResponse({
                "ok": True,
                "policy_suggestions": [
                    {"content": s.content, "source_agent_name": s.source_agent_name, "reason": s.reason}
                    for s in result.policy_suggestions
                ],
                "personnel_suggestions": [
                    {
                        "type": s.type, "content": s.content,
                        "source_agent_name": s.source_agent_name,
                        "target_person_name": s.target_person_name,
                        "target_position_name": s.target_position_name,
                        "reason": s.reason,
                    }
                    for s in result.personnel_suggestions
                ],
            })

        # action == "execute"：执行推演
        edict_text = edict.strip() if edict.strip() else "（本回合无诏书，朝政如常）"
        summary = await engine.run_turn(edict_text)

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
            if summary.appointment_results:
                yield _sse("appointments", summary.appointment_results)
            yield _sse("era", summary.era)
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")
```

- [ ] **Step 2: 新增 /court/start 路由（推演后早朝）**

在 `/court/interject` 路由之后新增：

```python
    @app.post("/court/start")
    async def court_start() -> StreamingResponse:
        """推演完成后启动早朝：百官对推演结果议政。"""
        court_speeches: list[dict] = []
        try:
            court_speeches = await engine.start_court_phase()
        except Exception:
            pass

        async def event_stream():
            if court_speeches:
                yield _sse("court_round", {
                    "speeches": court_speeches,
                    "round": 1,
                    "can_interject": engine.get_court_session_active(),
                })
            else:
                yield _sse("court_skip", {"reason": "无官员在朝"})
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")
```

- [ ] **Step 3: 清理不再使用的旧路由（可选）**

保留 `/court/end` 和 `/edict` 路由以兼容旧存档/测试，但前端不再调用。

- [ ] **Step 4: 验证语法正确**

Run: `python -c "from src.web.routes import register; print('OK')"`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add src/web/routes.py
git commit -m "feat: two-step next_turn and post-deduction court start"
```

---

### Task 6: 前端 - 对话建议确认模态框

**Files:**
- Modify: `src/web/templates/index.html`

- [ ] **Step 1: 在 HTML 中新增确认模态框**

在 `dialogue-overlay`（第303行）之后、`</body>` 之前新增：

```html
  <!-- 对话建议确认模态框 -->
  <div class="modal-overlay" id="extract-modal">
    <div class="modal-box" style="width:700px">
      <div class="modal-header">
        <h3>📜 对话建议确认</h3>
        <button class="modal-close" onclick="closeModal('extract-modal')">&times;</button>
      </div>
      <div class="modal-body" id="extract-body" style="max-height:60vh;overflow-y:auto">
        <div style="color:var(--muted)">提取中…</div>
      </div>
      <div class="modal-footer">
        <button onclick="confirmExtract()" style="background:var(--accent)">确认采纳</button>
        <button onclick="skipExtract()" style="background:var(--muted)">全部忽略</button>
      </div>
    </div>
  </div>
```

- [ ] **Step 2: 新增提取确认相关 CSS 样式**

在 `</style>` 之前新增：

```css
    .extract-section { margin:0.5rem 0; }
    .extract-section .section-title { font-size:0.9rem; color:var(--accent); font-weight:bold; margin-bottom:0.3rem; }
    .extract-item { display:flex; align-items:flex-start; gap:0.5rem; background:var(--bg); padding:0.5rem; margin:0.3rem 0; border:1px solid var(--border); font-size:0.85rem; }
    .extract-item input[type="checkbox"] { margin-top:0.2rem; }
    .extract-item .content { flex:1; }
    .extract-item .source { color:var(--muted); font-size:0.78rem; }
    .extract-item .reason { color:var(--text); font-size:0.82rem; margin-top:0.2rem; }
    .extract-item.personnel { border-left:3px solid var(--danger); }
    .extract-item.policy { border-left:3px solid var(--accent); }
```

- [ ] **Step 3: 新增提取确认相关 JavaScript**

在 `renderPendingEdicts` 函数之后、`nextTurn` 函数之前新增：

```javascript
    // ---- 对话建议提取 ----
    let extractedData = null;  // 暂存提取结果

    async function nextTurn() {
      // 第一步：提取对话建议
      document.getElementById('sim-overlay').classList.add('active');
      document.getElementById('status').textContent = '提取对话建议…';
      try {
        const fd = new FormData();
        fd.append('action', 'extract');
        const resp = await fetch('/next_turn', { method: 'POST', body: fd });
        const data = await resp.json();
        if (!data.ok) { throw new Error(data.error || '提取失败'); }
        extractedData = data;
        showExtractModal(data);
      } catch (err) {
        document.getElementById('status').textContent = '提取失败：' + err;
      } finally {
        document.getElementById('sim-overlay').classList.remove('active');
      }
    }

    function showExtractModal(data) {
      const body = document.getElementById('extract-body');
      let html = '';

      // 政策建议
      const policies = data.policy_suggestions || [];
      html += '<div class="extract-section">';
      html += '<div class="section-title">📜 政策建议（默认采纳）</div>';
      if (policies.length === 0) {
        html += '<div style="color:var(--muted);font-size:0.85rem">无</div>';
      } else {
        policies.forEach((s, i) => {
          html += `<div class="extract-item policy">
            <input type="checkbox" id="ext-policy-${i}" checked />
            <div class="content">
              <div>${s.content}</div>
              <div class="source">来自：${s.source_agent_name}${s.reason ? ' · ' + s.reason : ''}</div>
            </div>
          </div>`;
        });
      }
      html += '</div>';

      // 人事任免
      const personnel = data.personnel_suggestions || [];
      html += '<div class="extract-section">';
      html += '<div class="section-title">👤 人事任免（需您同意）</div>';
      if (personnel.length === 0) {
        html += '<div style="color:var(--muted);font-size:0.85rem">无</div>';
      } else {
        personnel.forEach((s, i) => {
          const label = s.type === 'appoint' ? '举荐' : '弹劾';
          html += `<div class="extract-item personnel">
            <input type="checkbox" id="ext-personnel-${i}" />
            <div class="content">
              <div>${s.content}</div>
              <div class="source">${label}自：${s.source_agent_name}${s.reason ? ' · ' + s.reason : ''}</div>
              ${s.target_person_name ? `<div class="reason">目标：${s.target_person_name}${s.target_position_name ? ' → ' + s.target_position_name : ''}</div>` : ''}
            </div>
          </div>`;
        });
      }
      html += '</div>';

      body.innerHTML = html;
      openModal('extract-modal');
    }

    function confirmExtract() {
      const edicts = [];
      // 收集选中的政策建议
      const policies = extractedData.policy_suggestions || [];
      policies.forEach((s, i) => {
        const cb = document.getElementById('ext-policy-' + i);
        if (cb && cb.checked) edicts.push(s.content);
      });
      // 收集选中的人事任免
      const personnel = extractedData.personnel_suggestions || [];
      personnel.forEach((s, i) => {
        const cb = document.getElementById('ext-personnel-' + i);
        if (cb && cb.checked) edicts.push(s.content);
      });
      closeModal('extract-modal');

      // 写入待颁列表
      for (const e of edicts) {
        pendingEdicts.push(e);
      }
      renderPendingEdicts();
      document.getElementById('status').textContent = '已添加 ' + edicts.length + ' 条建议到待颁诏令，可继续编辑或点击"下一回合"执行';
    }

    function skipExtract() {
      closeModal('extract-modal');
      document.getElementById('status').textContent = '已忽略所有建议，可继续操作';
    }
```

- [ ] **Step 4: 修改"下一回合"按钮文案和逻辑**

将 `renderPendingEdicts` 中的"下一回合 ▶"按钮（第249行）改为两步文案。在 `renderPendingEdicts` 函数中，当 `pendingEdicts.length > 0` 时显示"执行推演 ▶"，否则显示"下一回合 ▶"：

```javascript
    function renderPendingEdicts() {
      const container = document.getElementById('pending-edicts');
      const list = document.getElementById('pending-list');
      if (pendingEdicts.length === 0) {
        container.style.display = 'none';
        return;
      }
      container.style.display = 'block';
      list.innerHTML = pendingEdicts.map((e, i) =>
        `<div class="pending-item"><span class="idx">${i+1}.</span><span class="text">${e}</span><button class="remove" onclick="removeEdict(${i})">✕</button></div>`
      ).join('');
      // 有诏书时按钮显示"执行推演"
      document.getElementById('submit-btn').textContent = '执行推演 ▶';
    }
```

同时修改 `clearEdicts` 函数，清空后恢复按钮文案：

```javascript
    function clearEdicts() {
      pendingEdicts = [];
      renderPendingEdicts();
      document.getElementById('submit-btn').textContent = '下一回合 ▶';
    }
```

- [ ] **Step 5: 验证 HTML 语法正确**

Run: `python -c "from src.web.templates import index; print('OK')"` 或手动检查模板无语法错误。

- [ ] **Step 6: Commit**

```bash
git add src/web/templates/index.html
git commit -m "feat: add dialogue extraction confirmation modal"
```

---

### Task 7: 前端 - 执行推演 + 早朝后置

**Files:**
- Modify: `src/web/templates/index.html`

- [ ] **Step 1: 新增 executeTurn 函数（第二步：执行推演）**

在 `nextTurn` 函数之后新增：

```javascript
    // ---- 执行推演（第二步） ----
    async function executeTurn() {
      document.getElementById('sim-overlay').classList.add('active');
      const btn = document.getElementById('submit-btn');
      btn.disabled = true;
      document.getElementById('status').textContent = '推演中…';

      // 合并待颁诏令
      const edictText = pendingEdicts.length > 0
        ? pendingEdicts.map((e, i) => `${i+1}. ${e}`).join('\n')
        : '';
      pendingEdicts = [];
      renderPendingEdicts();
      document.getElementById('submit-btn').textContent = '下一回合 ▶';

      // 创建回合展示区域
      const turn = document.createElement('div'); turn.className = 'turn'; turn.id = 'current-turn';
      document.getElementById('dialog').prepend(turn);
      turn.innerHTML = '<div class="meta">推演中…</div>';

      try {
        const fd = new FormData();
        fd.append('action', 'execute');
        if (edictText) fd.append('edict', edictText);
        const resp = await fetch('/next_turn', { method: 'POST', body: fd });
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let narrative = '', executionList = [], deltaApplied = {}, deltaClipped = {};
        let newEvents = [], resolvedEvents = [], failDelta = {}, audienceList = [];
        let appointmentResults = [];

        while (true) {
          const {done, value} = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, {stream: true});
          const lines = buffer.split('\n');
          buffer = lines.pop();
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const payload = line.slice(6).trim();
            if (payload === '[DONE]') continue;
            try {
              const evt = JSON.parse(payload);
              const t = evt.type, d = evt.data;
              if (t === 'narrative') narrative = d || '';
              else if (t === 'execution') executionList = d || [];
              else if (t === 'delta') { deltaApplied = (d && d.applied) || {}; deltaClipped = (d && d.clipped) || {}; lastDelta = deltaApplied; }
              else if (t === 'new_events') newEvents = d || [];
              else if (t === 'resolved') resolvedEvents = d || [];
              else if (t === 'fail') failDelta = d || {};
              else if (t === 'audience') audienceList = d || [];
              else if (t === 'appointments') appointmentResults = d || [];
            } catch(e) {}
          }
        }

        // 渲染推演结果
        turn.innerHTML = renderTurnCard(edictText, '', narrative, executionList, deltaApplied, newEvents, resolvedEvents, failDelta, audienceList, appointmentResults);
        refreshState();

        // 推演完成后自动进入早朝
        await startPostCourt(turn);
      } catch (err) {
        turn.innerHTML = '<div class="narrative">推演失败：' + err + '</div>';
      } finally {
        document.getElementById('sim-overlay').classList.remove('active');
        btn.disabled = false;
      }
    }
```

- [ ] **Step 2: 新增 startPostCourt 函数（推演后早朝）**

在 `executeTurn` 之后新增：

```javascript
    // ---- 推演后早朝 ----
    let courtActive = false;

    async function startPostCourt(turn) {
      document.getElementById('status').textContent = '早朝开始…';

      try {
        const resp = await fetch('/court/start', { method: 'POST' });
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let courtHtml = '';

        while (true) {
          const {done, value} = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, {stream: true});
          const lines = buffer.split('\n');
          buffer = lines.pop();
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const payload = line.slice(6).trim();
            if (payload === '[DONE]') continue;
            try {
              const evt = JSON.parse(payload);
              if (evt.type === 'court_round') {
                courtHtml = renderCourtRound(evt.data);
                courtActive = evt.data.can_interject;
              } else if (evt.type === 'court_skip') {
                courtActive = false;
                turn.innerHTML += '<div class="meta" style="color:var(--muted)">无官员在朝</div>';
                return;
              }
            } catch(e) {}
          }
          if (courtHtml) {
            turn.innerHTML += courtHtml;
          }
        }

        if (courtActive) {
          showCourtInput(turn);
        }
        document.getElementById('status').textContent = courtActive ? '早朝进行中，可插话或结束早朝' : '早朝结束';
      } catch (err) {
        turn.innerHTML += '<div class="meta" style="color:var(--danger)">早朝失败：' + err + '</div>';
      }
    }
    ```

- [ ] **Step 3: 修改"下一回合"按钮的 onclick 逻辑**

将 `submit-btn` 的 `onclick` 从 `nextTurn()` 改为根据是否有待颁诏令决定调用 `nextTurn()`（提取）还是 `executeTurn()`（执行）：

```javascript
    // 修改 renderPendingEdicts 中的按钮
    // 在 pending-list 后的按钮区域：
    <button type="button" id="submit-btn" onclick="onSubmitTurn()" ...>
    
    // 新增 onSubmitTurn 函数
    function onSubmitTurn() {
      if (pendingEdicts.length > 0) {
        executeTurn();
      } else {
        nextTurn();
      }
    }
```

将 HTML 中 `submit-btn` 的 `onclick="nextTurn()"` 改为 `onclick="onSubmitTurn()"`。

- [ ] **Step 4: 修改 renderTurnCard 支持 appointment_results**

修改 `renderTurnCard` 函数（第798行），在"其他"章节前新增任免结果展示：

```javascript
    function renderTurnCard(edictText, courtHtml, narrative, executionList, deltaApplied, newEvents, resolvedEvents, failDelta, audienceList, appointmentResults) {
      let html = '';
      // ... 原有代码 ...

      // 任免结果章节
      if (appointmentResults && appointmentResults.length) {
        html += '<div class="turn-section"><div class="section-label">👤 任免结果</div>';
        html += appointmentResults.map(r => {
          if (r.action === 'appoint') {
            return r.ok
              ? `<div class="meta" style="color:var(--good)">任命 ${r.person} 为 ${r.position}</div>`
              : `<div class="meta" style="color:var(--danger)">任命 ${r.person} 失败：${r.error}</div>`;
          } else {
            return r.ok
              ? `<div class="meta" style="color:var(--good)">罢免 ${r.person}</div>`
              : `<div class="meta" style="color:var(--danger)">罢免 ${r.person} 失败：${r.error}</div>`;
          }
        }).join('');
        html += '</div>';
      }

      // ... 原有其他章节 ...
    }
```

- [ ] **Step 5: 修改 renderHistory 支持 appointment_results**

在 `renderHistory` 函数（第873行）的 turn_history 渲染中新增任免结果展示：

```javascript
        // 任免结果
        if (h.appointment_results && h.appointment_results.length) {
          html += '<div class="turn-section"><div class="section-label">👤 任免结果</div>';
          html += h.appointment_results.map(r => {
            if (r.action === 'appoint') {
              return r.ok
                ? `<div class="meta" style="color:var(--good)">任命 ${r.person} 为 ${r.position}</div>`
                : `<div class="meta" style="color:var(--danger)">任命 ${r.person} 失败：${r.error}</div>`;
            } else {
              return r.ok
                ? `<div class="meta" style="color:var(--good)">罢免 ${r.person}</div>`
                : `<div class="meta" style="color:var(--danger)">罢免 ${r.person} 失败：${r.error}</div>`;
            }
          }).join('');
          html += '</div>';
        }
```

- [ ] **Step 6: 验证无语法错误**

手动检查 HTML 中 JavaScript 语法正确，无未闭合的标签。

- [ ] **Step 7: Commit**

```bash
git add src/web/templates/index.html
git commit -m "feat: post-deduction court and appointment results display"
```

---

### Task 8: 测试验证

**Files:**
- Modify: `tests/test_web.py` (更新路由测试)
- Create: `tests/test_extraction.py` (提取逻辑测试)

- [ ] **Step 1: 编写提取逻辑单元测试**

创建 `tests/test_extraction.py`：

```python
"""测试对话诏书提取逻辑。"""

import pytest
from src.core.game_engine import ExtractedSuggestion, ExtractionResult


class TestExtractedSuggestion:
    def test_policy_suggestion(self):
        s = ExtractedSuggestion(
            type="policy", content="减免陕西赋税",
            source_agent_id="hu_bu", source_agent_name="户部尚书",
        )
        assert s.type == "policy"
        assert s.content == "减免陕西赋税"

    def test_appoint_suggestion(self):
        s = ExtractedSuggestion(
            type="appoint", content="举荐李自成为陕西巡抚",
            source_agent_id="bing_bu", source_agent_name="兵部尚书",
            target_person_name="李自成",
            target_position_name="陕西巡抚",
        )
        assert s.type == "appoint"
        assert s.target_person_name == "李自成"

    def test_extraction_result_empty(self):
        r = ExtractionResult()
        assert r.policy_suggestions == []
        assert r.personnel_suggestions == []

    def test_extraction_result_with_items(self):
        r = ExtractionResult(
            policy_suggestions=[
                ExtractedSuggestion(type="policy", content="a", source_agent_id="x", source_agent_name="X"),
            ],
            personnel_suggestions=[
                ExtractedSuggestion(type="appoint", content="b", source_agent_id="y", source_agent_name="Y"),
            ],
        )
        assert len(r.policy_suggestions) == 1
        assert len(r.personnel_suggestions) == 1
```

- [ ] **Step 2: 运行测试**

Run: `pytest tests/test_extraction.py -v`
Expected: 4 passed

- [ ] **Step 3: 运行现有测试确保无回归**

Run: `pytest tests/ -v`
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_extraction.py
git commit -m "test: add extraction dataclass unit tests"
```
