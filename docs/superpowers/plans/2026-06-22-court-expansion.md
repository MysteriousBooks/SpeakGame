# 开局朝臣扩充 + 职务显示 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 开局在朝官员从 3 人扩充为 8 人（六部各一人 + 魏忠贤 + 百姓），每个官员显示职务，魏忠贤变为可交互角色。

**Architecture:**
- PersonaCard 新增 `position` 字段，YAML 中配置职务
- 新增角色用 `recruitment_condition: 开局在朝` 标记，`_setup_initial_court()` 自动激活
- 前端 state 返回 position，列表和弹窗显示职务

**Tech Stack:** Python dataclasses, YAML, Jinja2, pytest

---

## 文件结构

### 修改文件
- `src/agents/base_agent.py` — PersonaCard 新增 position 字段
- `src/agents/personas/minister_finance.yaml` — 加 position
- `src/agents/personas/minister_war.yaml` — 加 position
- `src/agents/personas/common_people.yaml` — 加 position
- `src/agents/personas/historical_figures.yaml` — 各人物加 position + 新增 4 角色
- `src/core/game_engine.py` — `_setup_initial_court()` 改为按 recruitment_condition 激活
- `src/web/templates/index.html` — 显示职务
- `tests/test_web.py` — 验证开局 8 人

---

### Task 1: PersonaCard 新增 position 字段

**Files:**
- Modify: `src/agents/base_agent.py`

- [ ] **Step 1: 给 PersonaCard 添加 position 字段**

```python
@dataclass
class PersonaCard:
    """角色卡（含系统元数据，但 to_prompt_card 不输出元信息）。"""
    id: str = ""
    name: str = ""
    courtesy: str = ""
    position: str = ""  # 新增：官职，如"户部尚书"
    faction: str = ""
    skills: list[str] = field(default_factory=list)
    personality: str = ""
    relations: dict = field(default_factory=dict)
    # 系统元数据（不注入 agent 提示词）
    historical_alignment: str = ""
    born_year: int = 0
    historical_death_year: int = 9999
    death_cause: dict = field(default_factory=dict)
    recruitment_condition: str = ""
```

- [ ] **Step 2: 更新 from_dict 解析 position**

```python
@classmethod
def from_dict(cls, d: dict) -> "PersonaCard":
    return cls(
        id=d["id"],
        name=d["name"],
        courtesy=d.get("courtesy", ""),
        position=d.get("position", ""),
        faction=d.get("faction", ""),
        skills=list(d.get("skills", [])),
        personality=d.get("personality", ""),
        relations=dict(d.get("relations", {})),
        historical_alignment=d.get("historical_alignment", ""),
        born_year=int(d.get("born_year", 0)),
        historical_death_year=int(d.get("historical_death_year", 9999)),
        death_cause=dict(d.get("death_cause", {})),
        recruitment_condition=d.get("recruitment_condition", ""),
    )
```

- [ ] **Step 3: 更新 to_prompt_card 输出职务**

```python
def to_prompt_card(self) -> str:
    lines = [
        f"姓名：{self.name}" + (f"（字 {self.courtesy}）" if self.courtesy else ""),
        f"官职：{self.position}" if self.position else "",
        f"派系：{self.faction}",
        f"擅长：{'、'.join(self.skills) if self.skills else '无'}",
        f"性格：{self.personality}",
        f"关系网：{self._fmt_relations()}",
    ]
    return "\n".join(filter(None, lines))
```

- [ ] **Step 4: 运行测试**

Run: `cd D:/project/speakGame && .venv/Scripts/python.exe -m pytest tests/ -x -q -k "not sse"`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add src/agents/base_agent.py
git commit -m "feat: add position field to PersonaCard"
```

---

### Task 2: 现有角色 YAML 加 position

**Files:**
- Modify: `src/agents/personas/minister_finance.yaml`
- Modify: `src/agents/personas/minister_war.yaml`
- Modify: `src/agents/personas/common_people.yaml`

- [ ] **Step 1: 三个 YAML 文件各加 position 字段**

`minister_finance.yaml` 在 `name` 后加一行：
```yaml
position: 户部尚书
```

`minister_war.yaml`：
```yaml
position: 兵部尚书
```

`common_people.yaml`：
```yaml
position: 百姓
```

- [ ] **Step 2: 运行测试**

Run: `cd D:/project/speakGame && .venv/Scripts/python.exe -m pytest tests/ -x -q -k "not sse"`
Expected: all tests pass

- [ ] **Step 3: Commit**

```bash
git add src/agents/personas/
git commit -m "feat: add position to existing persona YAML files"
```

---

### Task 3: historical_figures.yaml 加 position + 新增 4 角色

**Files:**
- Modify: `src/agents/personas/historical_figures.yaml`

- [ ] **Step 1: 给现有 7 位历史人物加 position 字段**

每个 figure 加一行 `position:`，例如：
```yaml
- id: yuan_chonghuan
  name: 袁崇焕
  courtesy: 元素
  position: 辽东巡抚
  ...
```

各人物职务：
- 袁崇焕 → `position: 辽东巡抚`
- 孙传庭 → `position: 陕西巡抚`
- 洪承畴 → `position: 三边总督`
- 卢象升 → `position: 大名知府`
- 杨嗣昌 → `position: 兵部侍郎`
- 温体仁 → `position: 礼部尚书`
- 周延儒 → `position: 内阁大学士`

- [ ] **Step 2: 在 figures 列表末尾新增 4 个角色**

```yaml
  - id: wang_yongguang
    name: 王永光
    courtesy: 有孚
    position: 吏部尚书
    born_year: 1561
    historical_death_year: 1638
    death_cause:
      type: natural
      desc: 病亡
    faction: 独相派
    skills: [铨选, 吏治, 党争]
    historical_alignment: 争议
    personality: 老成持重，善铨选，周旋于党争之间
    relations: {同僚: 温体仁}
    recruitment_condition: 开局在朝

  - id: qiao_yunsheng
    name: 乔允升
    courtesy: 吉甫
    position: 刑部尚书
    born_year: 1557
    historical_death_year: 1635
    death_cause:
      type: natural
      desc: 病亡
    faction: 循吏系
    skills: [刑名, 司法, 审案]
    historical_alignment: 正派
    personality: 刚正不阿，精于刑名，持法公允
    relations: {同僚: 毕自严}
    recruitment_condition: 开局在朝

  - id: liu_zunxian
    name: 刘遵宪
    courtesy: 可权
    position: 工部尚书
    born_year: 1565
    historical_death_year: 1640
    death_cause:
      type: natural
      desc: 病亡
    faction: 循吏系
    skills: [营建, 水利, 屯田]
    historical_alignment: 正派
    personality: 勤勉务实，精于工程营造
    relations: {同僚: 毕自严}
    recruitment_condition: 开局在朝

  - id: wei_zhongxian
    name: 魏忠贤
    courtesy: ""
    position: 司礼监掌印太监
    born_year: 1568
    historical_death_year: 1628
    death_cause:
      type: suicide
      desc: 崇祯元年被贬凤阳，途中自缢
    faction: 阉党
    skills: [权术, 特务, 党争, 内廷]
    historical_alignment: 反派
    personality: 阴狠专权，善揣摩帝意，结党营私，权倾朝野
    relations: {党羽: 阉党余孽, 政敌: 东林党}
    recruitment_condition: 开局在朝
```

- [ ] **Step 3: 运行测试**

Run: `cd D:/project/speakGame && .venv/Scripts/python.exe -m pytest tests/ -x -q -k "not sse"`
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add src/agents/personas/historical_figures.yaml
git commit -m "feat: add position to historical figures and add 4 new court officials"
```

---

### Task 4: 开局激活逻辑改为按 recruitment_condition

**Files:**
- Modify: `src/core/game_engine.py`

- [ ] **Step 1: 修改 _setup_initial_court()**

将硬编码的 `_INITIAL_COURT` 列表替换为按 `recruitment_condition` 过滤：

```python
def _setup_initial_court(self) -> None:
    """开局内阁：激活所有 recruitment_condition='开局在朝' 的角色。"""
    era = self.state.era_label()
    for inst in list(self.roster.instances.values()):
        if inst.persona.recruitment_condition == "开局在朝":
            self.roster.recruit(inst.persona.id, self.role_llm, era)
```

同时删除 `_INITIAL_COURT` 常量（第 28 行）：
```python
# 删除这一行：
_INITIAL_COURT = ["minister_finance.yaml", "minister_war.yaml", "common_people.yaml"]
```

- [ ] **Step 2: 运行测试**

Run: `cd D:/project/speakGame && .venv/Scripts/python.exe -m pytest tests/ -x -q -k "not sse"`
Expected: all tests pass

- [ ] **Step 3: Commit**

```bash
git add src/core/game_engine.py
git commit -m "feat: activate court officials by recruitment_condition"
```

---

### Task 5: 前端显示职务

**Files:**
- Modify: `src/web/templates/index.html`

- [ ] **Step 1: state_snapshot 返回 position**

`src/core/game_engine.py` 中 `state_snapshot()` 的 `active_agents` 列表已包含 `id`、`name`、`dialogue`，加一个 `position`：

```python
"active_agents": [
    {
        "id": a.id,
        "name": a.name,
        "position": a.persona.position if hasattr(a, 'persona') else '',
        "dialogue": inst.dialogue_memory.to_dict() if (inst := self.roster.get(a.id)) else {},
    }
    for a in self.roster.active_agents()
],
```

- [ ] **Step 2: 在朝百官列表显示职务**

`index.html` 中 "在朝百官" 的渲染改为：

```html
<h2>在朝百官（点击可问询）</h2>
<div class="agents" id="agents">
  {% for a in state.active_agents %}<span onclick="openDialogue('{{ a.id }}','{{ a.name }}')">{{ a.name }}{% if a.position %}（{{ a.position }}）{% endif %}</span>{% endfor %}
</div>
```

- [ ] **Step 3: 对话弹窗标题显示职务**

`openDialogue()` 函数中标题改为：

```javascript
function openDialogue(agentId, agentName) {
  currentDialogueAgent = agentId;
  // 从 state 中查找职务
  fetch('/state').then(r => r.json()).then(s => {
    const agent = (s.active_agents || []).find(a => a.id === agentId);
    const title = agent && agent.position ? agentName + ' · ' + agent.position : agentName;
    document.getElementById('dialogue-agent-name').textContent = title;
  });
  ...
```

- [ ] **Step 4: refreshState 也显示职务**

```javascript
document.getElementById('agents').innerHTML = (s.active_agents||[]).map(a=>
  `<span onclick="openDialogue('${a.id}','${a.name}')">${a.name}${a.position ? '（' + a.position + '）' : ''}</span>`
).join('');
```

- [ ] **Step 5: 运行测试**

Run: `cd D:/project/speakGame && .venv/Scripts/python.exe -m pytest tests/ -x -q -k "not sse"`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add src/core/game_engine.py src/web/templates/index.html
git commit -m "feat: display position in court list and dialogue popup"
```

---

### Task 6: 测试验证

**Files:**
- Modify: `tests/test_web.py`

- [ ] **Step 1: 添加开局朝臣验证测试**

```python
def test_initial_court_has_eight_agents(client):
    """开局应有 8 位在朝官员（六部 + 魏忠贤 + 百姓）。"""
    s = client.get("/state").json()
    ids = {a["id"] for a in s["active_agents"]}
    expected = {
        "minister_finance", "minister_war", "common_people",
        "wang_yongguang", "qiao_yunsheng", "liu_zunxian",
        "wei_zhongxian", "wen_tiren",
    }
    missing = expected - ids
    assert not missing, f"缺少开局官员: {missing}"


def test_agents_have_position(client):
    """每个 active agent 应有 position 字段。"""
    s = client.get("/state").json()
    for a in s["active_agents"]:
        assert "position" in a, f"{a['name']} 缺少 position"
        assert a["position"], f"{a['name']} position 为空"


def test_wei_zhongxian_is_interactable(client):
    """魏忠贤应在朝且可对话。"""
    s = client.get("/state").json()
    wei = next((a for a in s["active_agents"] if a["id"] == "wei_zhongxian"), None)
    assert wei is not None, "魏忠贤不在朝"
    assert wei["position"] == "司礼监掌印太监"
```

- [ ] **Step 2: 运行测试**

Run: `cd D:/project/speakGame && .venv/Scripts/python.exe -m pytest tests/test_web.py -x -v -k "not sse"`
Expected: all tests pass

- [ ] **Step 3: 全量测试**

Run: `cd D:/project/speakGame && .venv/Scripts/python.exe -m pytest tests/ -x -q -k "not sse"`
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_web.py
git commit -m "test: verify initial court has 8 officials with positions"
```

---

## 自检清单

- [ ] Spec 覆盖：position 字段（Task 1）、YAML 配置（Task 2-3）、激活逻辑（Task 4）、前端显示（Task 5）、测试（Task 6）
- [ ] 无占位符：所有代码块包含完整实现
- [ ] 类型一致性：`position` 字段名在 Task 1 定义，Task 2-5 使用一致
- [ ] 测试覆盖：开局 8 人验证 + position 字段验证 + 魏忠贤可交互验证
