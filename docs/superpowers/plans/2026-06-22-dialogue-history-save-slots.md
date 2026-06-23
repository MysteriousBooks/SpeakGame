# 对话历史 + 存档槽位 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为朝臣对话添加持久化历史记录，回合结束时压缩为摘要，并实现多存档槽位系统。

**Architecture:**
- `DialogueMemory` 数据模型挂在 `AgentInstance` 上，随存档序列化
- 每次对话追加 `DialogueEntry`，回合结束时用 LLM 压缩为摘要
- 存档改为 `saves/slot_N/` 目录结构，支持多槽位

**Tech Stack:** Python dataclasses, FastAPI, Jinja2, pytest

---

## 文件结构

### 新建文件
- `src/agents/dialogue_memory.py` — DialogueEntry、DialogueMemory 数据模型
- `tests/test_dialogue_memory.py` — 对话记忆单元测试

### 修改文件
- `src/recruitment/roster.py` — AgentInstance 新增 dialogue_memory 字段 + 序列化
- `src/agents/base_agent.py` — _build_system() 注入对话摘要
- `src/web/routes.py` — /dialogue 记录对话、/save /load 改槽位、新增 /new_game /saves
- `src/core/game_engine.py` — 新增 compress_dialogues()、new_game()、save/load 改槽位
- `src/web/templates/index.html` — 存档槽位 UI、新游戏按钮

---

### Task 1: DialogueMemory 数据模型

**Files:**
- Create: `src/agents/dialogue_memory.py`
- Test: `tests/test_dialogue_memory.py`

- [ ] **Step 1: 创建 DialogueMemory 模块**

```python
# src/agents/dialogue_memory.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DialogueEntry:
    """单轮对话记录。"""
    role: str  # "player" | "agent"
    content: str
    turn: int

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content, "turn": self.turn}

    @classmethod
    def from_dict(cls, d: dict) -> DialogueEntry:
        return cls(role=d["role"], content=d["content"], turn=int(d.get("turn", 0)))


@dataclass
class DialogueMemory:
    """Agent 的对话记忆：压缩摘要 + 当前回合原始记录。"""
    compressed_summary: str = ""
    exchanges: list[DialogueEntry] = field(default_factory=list)

    def add_exchange(self, role: str, content: str, turn: int) -> None:
        self.exchanges.append(DialogueEntry(role=role, content=content, turn=turn))

    def clear_exchanges(self) -> None:
        self.exchanges.clear()

    def to_dict(self) -> dict:
        return {
            "compressed_summary": self.compressed_summary,
            "exchanges": [e.to_dict() for e in self.exchanges],
        }

    @classmethod
    def from_dict(cls, d: dict) -> DialogueMemory:
        return cls(
            compressed_summary=d.get("compressed_summary", ""),
            exchanges=[DialogueEntry.from_dict(e) for e in d.get("exchanges", [])],
        )
```

- [ ] **Step 2: 写单元测试**

```python
# tests/test_dialogue_memory.py
from src.agents.dialogue_memory import DialogueEntry, DialogueMemory


def test_dialogue_entry_roundtrip():
    e = DialogueEntry(role="player", content="你好", turn=1)
    d = e.to_dict()
    e2 = DialogueEntry.from_dict(d)
    assert e2.role == "player"
    assert e2.content == "你好"
    assert e2.turn == 1


def test_dialogue_memory_add_exchange():
    m = DialogueMemory()
    m.add_exchange("player", "你好", 1)
    m.add_exchange("agent", "臣在", 1)
    assert len(m.exchanges) == 2
    assert m.exchanges[0].role == "player"
    assert m.exchanges[1].role == "agent"


def test_dialogue_memory_clear():
    m = DialogueMemory()
    m.add_exchange("player", "你好", 1)
    m.clear_exchanges()
    assert len(m.exchanges) == 0


def test_dialogue_memory_roundtrip():
    m = DialogueMemory(compressed_summary="摘要")
    m.add_exchange("player", "你好", 1)
    d = m.to_dict()
    m2 = DialogueMemory.from_dict(d)
    assert m2.compressed_summary == "摘要"
    assert len(m2.exchanges) == 1
    assert m2.exchanges[0].content == "你好"


def test_dialogue_memory_empty_roundtrip():
    m = DialogueMemory()
    d = m.to_dict()
    m2 = DialogueMemory.from_dict(d)
    assert m2.compressed_summary == ""
    assert m2.exchanges == []
```

- [ ] **Step 3: 运行测试确认通过**

Run: `cd D:/project/speakGame && .venv/Scripts/python.exe -m pytest tests/test_dialogue_memory.py -v`
Expected: 5 passed

- [ ] **Step 4: Commit**

```bash
git add src/agents/dialogue_memory.py tests/test_dialogue_memory.py
git commit -m "feat: add DialogueMemory data model with serialization"
```

---

### Task 2: AgentInstance 集成 DialogueMemory

**Files:**
- Modify: `src/recruitment/roster.py`

- [ ] **Step 1: 给 AgentInstance 添加 dialogue_memory 字段**

在 `src/recruitment/roster.py` 的 `AgentInstance` dataclass 中新增字段：

```python
# 在文件顶部添加导入
from src.agents.dialogue_memory import DialogueMemory

# 在 AgentInstance 的字段列表中添加
@dataclass
class AgentInstance:
    persona: PersonaCard
    status: str = AVAILABLE
    factual: FactualMemory = field(default_factory=FactualMemory)
    narrative: NarrativeMemory = field(default_factory=NarrativeMemory)
    agent: BaseAgent | None = None
    loyalty: int = 70
    dissatisfaction: int = 0
    safety: int = 50
    dialogue_memory: DialogueMemory = field(default_factory=DialogueMemory)  # 新增
```

- [ ] **Step 2: 更新 AgentInstance.to_dict() 序列化**

```python
# 在 to_dict() 方法中添加 dialogue_memory
def to_dict(self) -> dict:
    return {
        "persona_id": self.persona.id,
        "status": self.status,
        "factual": self.factual.to_dict(),
        "narrative": self.narrative.to_dict(),
        "loyalty": self.loyalty,
        "dissatisfaction": self.dissatisfaction,
        "safety": self.safety,
        "dialogue_memory": self.dialogue_memory.to_dict(),  # 新增
    }
```

- [ ] **Step 3: 更新 AgentInstance 反序列化**

在 `Roster` 的 `_build_instance` 或 `from_dict` 逻辑中，加载时恢复 `dialogue_memory`：

找到 `Roster` 中从 dict 恢复 `AgentInstance` 的代码（在 `GameEngine.load()` 中，约第 277-294 行），添加：

```python
# 在 routes.py 的 load 函数中，恢复 roster 的部分添加：
inst.dialogue_memory = DialogueMemory.from_dict(inst_data.get("dialogue_memory", {}))
```

- [ ] **Step 4: 运行现有测试确保没破坏**

Run: `cd D:/project/speakGame && .venv/Scripts/python.exe -m pytest tests/ -x -q`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add src/recruitment/roster.py
git commit -m "feat: integrate DialogueMemory into AgentInstance with serialization"
```

---

### Task 3: 对话摘要注入 Agent Prompt

**Files:**
- Modify: `src/agents/base_agent.py`

- [ ] **Step 1: 在 _build_system() 中注入对话摘要**

修改 `_build_system()` 方法，在 prompt 末尾添加对话摘要：

```python
def _build_system(self, scene: str, tags: list[str] | None = None) -> str:
    factual_notes = self.factual.search(tags)
    factual_text = "\n".join(f"- {n.content}" for n in factual_notes) or "（无相关条目）"
    narrative_text = self.narrative.summary() or "（无）"
    prompt = self.agent_base_prompt
    prompt = (
        prompt.replace("{{era}}", self.era)
        .replace("{{persona_card}}", self.persona.to_prompt_card())
        .replace("{{factual_memory}}", factual_text)
        .replace("{{narrative_memory}}", narrative_text)
        .replace("{{scene}}", scene)
    )
    # 新增：注入对话历史摘要
    dialogue_summary = getattr(self, '_dialogue_summary', '')
    if dialogue_summary:
        prompt += (
            "\n\n## 你与皇帝的对话历史\n\n"
            f"以下是你们过往对话的精炼摘要，请基于此保持对话连贯：\n{dialogue_summary}"
        )
    return prompt
```

- [ ] **Step 2: 添加 set_dialogue_summary 方法**

```python
# 在 BaseAgent 类中添加
def set_dialogue_summary(self, summary: str) -> None:
    """设置对话历史摘要，供 _build_system 注入 prompt。"""
    self._dialogue_summary = summary
```

- [ ] **Step 3: 运行测试**

Run: `cd D:/project/speakGame && .venv/Scripts/python.exe -m pytest tests/ -x -q`
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add src/agents/base_agent.py
git commit -m "feat: inject dialogue summary into agent system prompt"
```

---

### Task 4: /dialogue 端点记录对话

**Files:**
- Modify: `src/web/routes.py`

- [ ] **Step 1: 修改 /dialogue 端点，追加对话记录并注入摘要**

```python
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
```

- [ ] **Step 2: 运行测试**

Run: `cd D:/project/speakGame && .venv/Scripts/python.exe -m pytest tests/ -x -q`
Expected: all tests pass

- [ ] **Step 3: Commit**

```bash
git add src/web/routes.py
git commit -m "feat: record dialogue exchanges and inject summary in /dialogue endpoint"
```

---

### Task 5: 回合结束对话压缩

**Files:**
- Modify: `src/core/game_engine.py`

- [ ] **Step 1: 在 GameEngine 中添加 compress_dialogues() 方法**

```python
# 在 GameEngine 类中添加
DIALOGUE_COMPRESS_PROMPT = (
    "你是一个精炼对话摘要的助手。请将以下皇帝与大臣的对话记录精炼为一段摘要（100-200字），"
    "保留关键信息：讨论的话题、大臣的立场、皇帝的决策、任何承诺或警告。\n\n"
    "如果已有历史摘要，请将新对话与历史摘要合并更新。\n\n"
    "历史摘要：{existing_summary}\n\n"
    "本轮新对话：\n{exchanges}\n\n"
    "请只输出精炼后的摘要，不要任何解释："
)

async def compress_dialogues(self) -> int:
    """压缩所有 active agent 的本轮对话记录。返回压缩的 agent 数量。"""
    compressed = 0
    for inst in self.roster.instances.values():
        if inst.status != "active" or not inst.dialogue_memory.exchanges:
            continue
        dm = inst.dialogue_memory
        # 构建压缩 prompt
        exchanges_text = "\n".join(
            f"{'帝' if e.role == 'player' else inst.persona.name}：{e.content}"
            for e in dm.exchanges
        )
        prompt = self.DIALOGUE_COMPRESS_PROMPT.format(
            existing_summary=dm.compressed_summary or "（无）",
            exchanges=exchanges_text,
        )
        try:
            new_summary = await self.role_llm.chat(
                [Message("user", prompt)],
                system="你是一个精炼摘要助手。",
                max_tokens=512,
                temperature=0.3,
            )
            dm.compressed_summary = new_summary.strip()
            dm.clear_exchanges()
            compressed += 1
        except Exception:
            # 压缩失败不阻塞回合，保留原始 exchanges 下次再试
            pass
    return compressed
```

- [ ] **Step 2: 在 _run_post_court() 末尾调用 compress_dialogues()**

在 `_run_post_court()` 方法的末尾（`return TurnSummary(...)` 之前），添加：

```python
# 压缩对话历史
await self.compress_dialogues()
```

- [ ] **Step 3: 运行测试**

Run: `cd D:/project/speakGame && .venv/Scripts/python.exe -m pytest tests/ -x -q`
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add src/core/game_engine.py
git commit -m "feat: add turn-end dialogue compression with LLM summarization"
```

---

### Task 6: 存档槽位系统

**Files:**
- Modify: `src/core/game_engine.py`
- Modify: `src/web/routes.py`

- [ ] **Step 1: 在 GameEngine 中添加 new_game() 和槽位 save/load**

```python
# 在 GameEngine 类中添加
def new_game(self) -> None:
    """重置引擎到初始状态（新游戏）。"""
    cfg = self.config
    from src.core.world_state import WorldState
    from src.finance.economy import FinanceParams
    from src.core.tasks import TaskSystem
    from src.core.audience import AudienceQueue
    from src.events.event_engine import EventEngine
    from src.recruitment.roster import Roster

    self.state = WorldState(cfg)
    self.finance = FinanceParams(cfg)
    self.roster = Roster(cfg)
    self.tasks = TaskSystem()
    self.audience = AudienceQueue()
    self.events = EventEngine(cfg)
    self.turn_history.clear()
    self._pending_edict = ""
    self._exam_gongshi = None
    self._exam_rankings = {}
    self._exam_year = 0

    # 开局激活初始官员
    era = self.state.era_label()
    for inst in list(self.roster.instances.values()):
        if inst.persona.recruitment_condition == "开局内阁":
            self.roster.recruit(inst.persona.id, self.role_llm, era)

SAVE_DIR = Path("saves")

def _slot_path(self, slot: int) -> Path:
    return self.SAVE_DIR / f"slot_{slot}"

def save_to_slot(self, slot: int) -> str:
    """保存到指定槽位。"""
    slot_dir = self._slot_path(slot)
    slot_dir.mkdir(parents=True, exist_ok=True)
    path = slot_dir / "state.json"
    self.save(str(path))
    # 额外保存 turn_history
    import json
    hist_path = slot_dir / "history.json"
    hist_path.write_text(
        json.dumps(self.turn_history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(slot_dir)

def load_from_slot(self, slot: int) -> None:
    """从指定槽位加载。"""
    slot_dir = self._slot_path(slot)
    path = slot_dir / "state.json"
    if not path.exists():
        raise FileNotFoundError(f"槽位 {slot} 无存档")
    self.load(str(path))
    # 恢复 turn_history
    import json
    hist_path = slot_dir / "history.json"
    if hist_path.exists():
        self.turn_history = json.loads(hist_path.read_text(encoding="utf-8"))

@staticmethod
def list_saves() -> list[dict]:
    """列出所有存档槽位信息。"""
    slots = []
    for i in range(1, 4):
        slot_dir = SAVE_DIR / f"slot_{i}"
        state_path = slot_dir / "state.json"
        if state_path.exists():
            import json
            data = json.loads(state_path.read_text(encoding="utf-8"))
            slots.append({
                "slot": i,
                "exists": True,
                "era": data.get("state", {}).get("era", ""),
                "turn": data.get("state", {}).get("turn", 0),
            })
        else:
            slots.append({"slot": i, "exists": False})
    return slots
```

- [ ] **Step 2: 更新路由：/save、/load 改槽位，新增 /new_game、/saves**

```python
# 替换原有的 /save 和 /load 路由

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
```

- [ ] **Step 3: 运行测试**

Run: `cd D:/project/speakGame && .venv/Scripts/python.exe -m pytest tests/ -x -q`
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add src/core/game_engine.py src/web/routes.py
git commit -m "feat: add save slot system with new_game endpoint"
```

---

### Task 7: 前端存档槽位 UI

**Files:**
- Modify: `src/web/templates/index.html`

- [ ] **Step 1: 替换存档/读档按钮为槽位弹窗**

在 HTML 的 toolbar 部分，替换原有的存档/读档按钮：

```html
<button onclick="openSaveModal()">存档</button>
<button onclick="openLoadModal()">读档</button>
<button onclick="newGame()" style="color:var(--danger)">新游戏</button>
```

- [ ] **Step 2: 添加存档/读档/新游戏弹窗 HTML**

在 `<!-- 对话弹窗 -->` 之前添加：

```html
<!-- 存档弹窗 -->
<div class="modal-overlay" id="save-modal">
  <div class="modal-box" style="width:400px">
    <div class="modal-header"><h3>存档</h3><button class="modal-close" onclick="closeModal('save-modal')">&times;</button></div>
    <div class="modal-body" id="save-body">加载中…</div>
  </div>
</div>

<!-- 读档弹窗 -->
<div class="modal-overlay" id="load-modal">
  <div class="modal-box" style="width:400px">
    <div class="modal-header"><h3>读档</h3><button class="modal-close" onclick="closeModal('load-modal')">&times;</button></div>
    <div class="modal-body" id="load-body">加载中…</div>
  </div>
</div>
```

- [ ] **Step 3: 添加 JavaScript 函数**

在 `refreshState()` 函数之前添加：

```javascript
// ---- 存档/读档/新游戏 ----
async function openSaveModal() {
  openModal('save-modal');
  const r = await fetch('/saves');
  const data = await r.json();
  document.getElementById('save-body').innerHTML = data.slots.map(s => {
    if (s.exists) {
      return `<div class="card"><span class="name">槽位 ${s.slot}</span><div class="meta">${s.era} · 第${s.turn}回合</div><button onclick="doSave(${s.slot})">覆盖存档</button></div>`;
    } else {
      return `<div class="card"><span class="name">槽位 ${s.slot}</span><div class="meta" style="color:var(--muted)">空</div><button onclick="doSave(${s.slot})">存档</button></div>`;
    }
  }).join('');
}

async function doSave(slot) {
  const fd = new FormData();
  fd.append('slot', slot);
  const r = await fetch('/save', {method:'POST', body: fd});
  const data = await r.json();
  if (data.ok) { alert('存档成功：槽位' + slot); closeModal('save-modal'); }
  else alert(data.error || '存档失败');
}

async function openLoadModal() {
  openModal('load-modal');
  const r = await fetch('/saves');
  const data = await r.json();
  document.getElementById('load-body').innerHTML = data.slots.map(s => {
    if (s.exists) {
      return `<div class="card"><span class="name">槽位 ${s.slot}</span><div class="meta">${s.era} · 第${s.turn}回合</div><button onclick="doLoad(${s.slot})">读档</button></div>`;
    } else {
      return `<div class="card"><span class="name">槽位 ${s.slot}</span><div class="meta" style="color:var(--muted)">空</div></div>`;
    }
  }).join('');
}

async function doLoad(slot) {
  if (!confirm('读档将覆盖当前进度，确定？')) return;
  const fd = new FormData();
  fd.append('slot', slot);
  const r = await fetch('/load', {method:'POST', body: fd});
  const data = await r.json();
  if (data.ok) { alert('读档成功'); location.reload(); }
  else alert(data.error || '读档失败');
}

async function newGame() {
  if (!confirm('新游戏将重置所有进度，确定？')) return;
  const r = await fetch('/new_game', {method:'POST'});
  const data = await r.json();
  if (data.ok) location.reload();
  else alert('新游戏失败');
}
```

- [ ] **Step 4: 运行测试**

Run: `cd D:/project/speakGame && .venv/Scripts/python.exe -m pytest tests/ -x -q`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add src/web/templates/index.html
git commit -m "feat: add save slot UI with new game button"
```

---

### Task 8: 集成测试

**Files:**
- Modify: `tests/test_web.py`（或新增 `tests/test_save_slots.py`）

- [ ] **Step 1: 写存档槽位集成测试**

```python
# 在 tests/test_web.py 末尾添加，或新建 tests/test_save_slots.py

import json
from pathlib import Path


def test_new_game(client):
    """新游戏重置状态。"""
    resp = client.post("/new_game")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "崇祯" in data["era"]


def test_save_and_load_slot(client):
    """存档到槽位并读档。"""
    # 先存档到槽位1
    resp = client.post("/save", data={"slot": 1})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # 验证存档文件存在
    assert Path("saves/slot_1/state.json").exists()

    # 列出存档
    resp = client.get("/saves")
    assert resp.status_code == 200
    slots = resp.json()["slots"]
    slot1 = [s for s in slots if s["slot"] == 1]
    assert len(slot1) == 1
    assert slot1[0]["exists"] is True

    # 读档
    resp = client.post("/load", data={"slot": 1})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_load_empty_slot(client):
    """读空槽位返回 404。"""
    resp = client.post("/load", data={"slot": 99})
    assert resp.status_code == 404


def test_dialogue_records_exchanges(client):
    """对话后 agent 应有对话记录。"""
    # 先推进一回合确保有 active agent
    resp = client.post("/next_turn", data={"edict": "test"})
    assert resp.status_code == 200

    # 找一个 active agent 对话
    state = client.get("/state").json()
    agents = state.get("active_agents", [])
    if not agents:
        return  # 无 agent 则跳过
    agent_id = agents[0]["id"]

    resp = client.post(f"/dialogue/{agent_id}", data={"message": "你好"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["public"] != ""

    # 验证对话记录存在
    state2 = client.get("/state").json()
    # 对话记录存在 roster 中，通过存档验证
    resp = client.post("/save", data={"slot": 1})
    assert resp.status_code == 200
    saved = json.loads(Path("saves/slot_1/state.json").read_text(encoding="utf-8"))
    roster = saved.get("roster", {}).get("instances", {})
    if agent_id in roster:
        dm = roster[agent_id].get("dialogue_memory", {})
        assert len(dm.get("exchanges", [])) >= 2  # player + agent
```

- [ ] **Step 2: 运行测试**

Run: `cd D:/project/speakGame && .venv/Scripts/python.exe -m pytest tests/test_web.py -x -v`
Expected: all tests pass

- [ ] **Step 3: 全量测试**

Run: `cd D:/project/speakGame && .venv/Scripts/python.exe -m pytest tests/ -x -q`
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test: add save slot and dialogue history integration tests"
```

---

## 自检清单

- [ ] 每个 spec 需求都有对应 task：对话历史存储（Task 1-2）、摘要注入（Task 3）、对话记录（Task 4）、回合压缩（Task 5）、存档槽位（Task 6-7）、测试（Task 8）
- [ ] 无占位符：所有代码块包含完整实现
- [ ] 类型一致性：DialogueMemory 的字段名在 Task 1 定义，Task 2-5 使用一致
- [ ] 测试覆盖：单元测试（Task 1）+ 集成测试（Task 8）
