# 吏部管理：官员任命与卸任系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现吏部管理面板，使玩家能直接任命/卸任官员，管理职务和人才库。

**Architecture:** 新增 CourtPosition/PositionManager 数据层，扩展 Roster/GameEngine 方法，新增 5 个 Web API 端点，前端新增吏部面板模态框。

**Tech Stack:** Python/FastAPI, Jinja2, pytest

---

### Task 1: PersonaCard 新增 gender/weaknesses 字段

**Files:**
- Modify: `src/agents/base_agent.py:36-71`
- Modify: `src/agents/personas/historical_figures.yaml`
- Modify: `src/recruitment/exam.py:135-173`
- Test: `tests/test_roster.py`

- [ ] **Step 1: 给 PersonaCard 添加 gender 和 weaknesses 字段**

在 `src/agents/base_agent.py` 的 PersonaCard dataclass 中新增两个字段：

```python
@dataclass
class PersonaCard:
    # ... 现有字段 ...
    gender: str = ""           # 男/女
    weaknesses: list[str] = field(default_factory=list)  # 缺点列表
```

在 `from_dict` 方法中解析新字段：

```python
@classmethod
def from_dict(cls, d: dict) -> "PersonaCard":
    return cls(
        # ... 现有字段 ...
        gender=d.get("gender", ""),
        weaknesses=list(d.get("weaknesses", [])),
    )
```

- [ ] **Step 2: 给 historical_figures.yaml 所有角色添加 gender 和 weaknesses**

为每个 figure 添加字段。示例：

```yaml
  - id: yuan_chonghuan
    name: 袁崇焕
    gender: 男
    weaknesses: [刚愎自用, 轻敌]
    # ... 其余字段不变 ...
```

所有 12 位历史角色均添加 `gender: 男` 和各自的 weaknesses：
- 袁崇焕: `[刚愎自用, 轻敌]`
- 孙传庭: `[恃勇轻进, 刚愎]`
- 洪承畴: `[优柔寡断, 明哲保身]`
- 卢象升: `[有勇无谋, 轻进]`
- 杨嗣昌: `[刚愎自用, 纸上谈兵]`
- 温体仁: `[阴柔专擅, 排挤同僚]`
- 周延儒: `[贪墨, 结党营私]`
- 王永光: `[圆滑, 明哲保身]`
- 乔允升: `[刻板, 不知变通]`
- 刘遵宪: `[过于谨慎, 效率低下]`
- 魏忠贤: `[专权跋扈, 结党营私]`

- [ ] **Step 3: 给 generate_jinshi_persona 添加 gender 和 weaknesses**

在 `src/recruitment/exam.py` 的 `generate_jinshi_persona` 函数中，新增随机性别和缺点：

```python
def generate_jinshi_persona(...):
    # ... 现有代码 ...
    gender = random.choice(["男", "女"])
    weaknesses = random.sample(["马虎", "贪墨", "刚愎", "怯懦", "刻板", "圆滑", "急躁", "懒散"], k=random.randint(1, 2))
    return PersonaCard(
        # ... 现有字段 ...
        gender=gender,
        weaknesses=weaknesses,
    )
```

注意：需要在文件顶部添加 `import random`（如果尚未导入）。

- [ ] **Step 4: 运行现有测试确保不破坏**

Run: `pytest tests/test_roster.py -v`
Expected: 所有测试通过

- [ ] **Step 5: Commit**

```bash
git add src/agents/base_agent.py src/agents/personas/historical_figures.yaml src/recruitment/exam.py
git commit -m "feat: add gender and weaknesses fields to PersonaCard"
```

---

### Task 2: CourtPosition 数据类 + PositionManager 管理类

**Files:**
- Create: `src/recruitment/positions.py`
- Test: `tests/test_positions.py`

- [ ] **Step 1: 创建 CourtPosition dataclass 和 PositionManager**

新建 `src/recruitment/positions.py`：

```python
"""职务管理：CourtPosition 数据类 + PositionManager 管理类。

设计要点：
- 职务是存档的一部分，每个存档可自定义
- 同一职务只能被一位官员占用
- 支持创建自定义职务
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CourtPosition:
    """朝廷职务。"""
    id: str
    name: str
    rank: str
    scope: str
    occupied_by: str | None = None  # persona_id，None=空缺

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "rank": self.rank,
            "scope": self.scope,
            "occupied_by": self.occupied_by,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CourtPosition":
        return cls(
            id=d["id"],
            name=d["name"],
            rank=d.get("rank", ""),
            scope=d.get("scope", ""),
            occupied_by=d.get("occupied_by"),
        )


# 默认职务列表（存档初始化时加载）
DEFAULT_POSITIONS = [
    # 六部
    {"id": "libu_rites", "name": "礼部尚书", "rank": "正二品", "scope": "掌礼仪祭祀科举"},
    {"id": "hubu_shangshu", "name": "户部尚书", "rank": "正二品", "scope": "掌全国财政"},
    {"id": "libu_personnel", "name": "吏部尚书", "rank": "正二品", "scope": "掌全国官吏铨选"},
    {"id": "bingbu_shangshu", "name": "兵部尚书", "rank": "正二品", "scope": "掌全国武官兵籍"},
    {"id": "xingbu_shangshu", "name": "刑部尚书", "rank": "正二品", "scope": "掌全国刑律狱政"},
    {"id": "gongbu_shangshu", "name": "工部尚书", "rank": "正二品", "scope": "掌全国工程营造"},
    # 都察院
    {"id": "zuo_duyushi", "name": "左都御史", "rank": "正二品", "scope": "掌都察院监察"},
    # 内阁
    {"id": "neige_daxueshi", "name": "内阁大学士", "rank": "正五品", "scope": "参预机务"},
    # 内廷
    {"id": "silijian_zhangyin", "name": "司礼监掌印太监", "rank": "正四品", "scope": "掌内廷批红"},
    # 地方
    {"id": "liaodong_xunfu", "name": "辽东巡抚", "rank": "正四品", "scope": "掌辽东军务"},
    {"id": "shanxi_xunfu", "name": "陕西巡抚", "rank": "正四品", "scope": "掌陕西军政"},
    {"id": "sanbian_zongdu", "name": "三边总督", "rank": "正三品", "scope": "掌三边军务"},
    {"id": "daming_zhifu", "name": "大名知府", "rank": "正四品", "scope": "掌大名府政务"},
    {"id": "bingbu_shilang", "name": "兵部侍郎", "rank": "正三品", "scope": "掌兵部事务"},
    # 翰林院
    {"id": "hanlin_xiuzhuan", "name": "翰林院修撰", "rank": "从六品", "scope": "掌修国史"},
    {"id": "hanlin_bianxiu", "name": "翰林院编修", "rank": "正七品", "scope": "掌修国史"},
    {"id": "hanlin_shujishi", "name": "翰林院庶吉士", "rank": "从七品", "scope": "储才学习"},
    # 监察/六部
    {"id": "liuke_jishizhong", "name": "六科给事中", "rank": "从七品", "scope": "监察六部"},
    {"id": "jiancha_yushi", "name": "监察御史", "rank": "从七品", "scope": "巡按地方"},
    {"id": "liubu_zhushi", "name": "六部主事", "rank": "正六品", "scope": "各部实务"},
    {"id": "zhixian", "name": "知县", "rank": "正七品", "scope": "掌一县民政"},
    {"id": "tuiguan", "name": "推官", "rank": "从七品", "scope": "府级司法"},
]


class PositionManager:
    """职务管理器：持有全部职务，管理占用/释放/查询。"""

    def __init__(self, positions: list[CourtPosition] | None = None) -> None:
        self._positions: list[CourtPosition] = positions or [
            CourtPosition(**p) for p in DEFAULT_POSITIONS
        ]

    def get_by_id(self, position_id: str) -> CourtPosition | None:
        return next((p for p in self._positions if p.id == position_id), None)

    def get_by_name(self, name: str) -> CourtPosition | None:
        return next((p for p in self._positions if p.name == name), None)

    def get_vacant(self) -> list[CourtPosition]:
        return [p for p in self._positions if p.occupied_by is None]

    def get_occupied(self) -> list[CourtPosition]:
        return [p for p in self._positions if p.occupied_by is not None]

    def get_all(self) -> list[CourtPosition]:
        return list(self._positions)

    def occupy(self, position_id: str, persona_id: str) -> CourtPosition:
        """占用一个职务。返回该职务。"""
        pos = self.get_by_id(position_id)
        if pos is None:
            raise KeyError(f"职务 {position_id} 不存在")
        if pos.occupied_by is not None:
            raise ValueError(f"职务 {pos.name} 已被占用")
        pos.occupied_by = persona_id
        return pos

    def release(self, position_id: str) -> CourtPosition:
        """释放一个职务（卸任时调用）。返回该职务。"""
        pos = self.get_by_id(position_id)
        if pos is None:
            raise KeyError(f"职务 {position_id} 不存在")
        pos.occupied_by = None
        return pos

    def release_by_persona(self, persona_id: str) -> list[CourtPosition]:
        """释放某官员占用的所有职务（卸任时调用）。返回被释放的职务列表。"""
        released = []
        for pos in self._positions:
            if pos.occupied_by == persona_id:
                pos.occupied_by = None
                released.append(pos)
        return released

    def create(self, name: str, rank: str, scope: str) -> CourtPosition:
        """创建自定义职务。"""
        pos_id = f"custom_{name}"
        if self.get_by_id(pos_id) is not None:
            raise ValueError(f"职务 {name} 已存在")
        pos = CourtPosition(id=pos_id, name=name, rank=rank, scope=scope)
        self._positions.append(pos)
        return pos

    def to_dict(self) -> list[dict]:
        return [p.to_dict() for p in self._positions]

    @classmethod
    def from_dict(cls, data: list[dict]) -> "PositionManager":
        return cls(positions=[CourtPosition.from_dict(d) for d in data])
```

- [ ] **Step 2: 编写 PositionManager 测试**

新建 `tests/test_positions.py`：

```python
"""测试职务管理模块。"""

import pytest

from src.recruitment.positions import CourtPosition, PositionManager


def test_default_positions_loaded():
    pm = PositionManager()
    assert len(pm.get_all()) == 23  # 默认 23 个职务
    assert pm.get_by_id("libu_rites") is not None


def test_vacant_positions():
    pm = PositionManager()
    vacant = pm.get_vacant()
    assert all(p.occupied_by is None for p in vacant)
    assert len(vacant) == 23  # 初始全部空缺


def test_occupy_position():
    pm = PositionManager()
    pos = pm.occupy("libu_rites", "wen_tiren")
    assert pos.occupied_by == "wen_tiren"
    assert pm.get_by_id("libu_rites").occupied_by == "wen_tiren"
    assert len(pm.get_vacant()) == 22
    assert len(pm.get_occupied()) == 1


def test_occupy_already_occupied_raises():
    pm = PositionManager()
    pm.occupy("libu_rites", "wen_tiren")
    with pytest.raises(ValueError, match="已被占用"):
        pm.occupy("libu_rites", "wang_yongguang")


def test_release_position():
    pm = PositionManager()
    pm.occupy("libu_rites", "wen_tiren")
    pos = pm.release("libu_rites")
    assert pos.occupied_by is None
    assert pm.get_by_id("libu_rites").occupied_by is None


def test_release_by_persona():
    pm = PositionManager()
    pm.occupy("libu_rites", "wen_tiren")
    pm.occupy("hubu_shangshu", "wen_tiren")
    released = pm.release_by_persona("wen_tiren")
    assert len(released) == 2
    assert pm.get_by_id("libu_rites").occupied_by is None
    assert pm.get_by_id("hubu_shangshu").occupied_by is None


def test_create_position():
    pm = PositionManager()
    pos = pm.create("东厂提督", "正四品", "掌东厂刑狱侦缉")
    assert pos.id == "custom_东厂提督"
    assert pm.get_by_id("custom_东厂提督") is not None
    assert len(pm.get_all()) == 24


def test_create_duplicate_raises():
    pm = PositionManager()
    pm.create("东厂提督", "正四品", "掌东厂")
    with pytest.raises(ValueError, match="已存在"):
        pm.create("东厂提督", "从四品", "重复")


def test_serialize_deserialize():
    pm = PositionManager()
    pm.occupy("libu_rites", "wen_tiren")
    pm.create("东厂提督", "正四品", "掌东厂")
    data = pm.to_dict()
    pm2 = PositionManager.from_dict(data)
    assert len(pm2.get_all()) == 24
    assert pm2.get_by_id("libu_rites").occupied_by == "wen_tiren"
    assert pm2.get_by_id("custom_东厂提督") is not None
```

- [ ] **Step 3: 运行测试**

Run: `pytest tests/test_positions.py -v`
Expected: 全部通过

- [ ] **Step 4: Commit**

```bash
git add src/recruitment/positions.py tests/test_positions.py
git commit -m "feat: add CourtPosition and PositionManager"
```

---

### Task 3: Roster 新增 get_talent_pool 方法

**Files:**
- Modify: `src/recruitment/roster.py:108-116`
- Test: `tests/test_roster.py`

- [ ] **Step 1: 添加 get_talent_pool 方法**

在 `src/recruitment/roster.py` 的 Roster 类中添加：

```python
def get_talent_pool(self) -> list[dict]:
    """返回人才库列表：available 历史人物 + dismissed 官员。"""
    pool = []
    for inst in self.instances.values():
        if inst.status in (AVAILABLE, DISMISSED):
            pool.append({
                "id": inst.persona.id,
                "name": inst.persona.name,
                "gender": inst.persona.gender,
                "skills": list(inst.persona.skills),
                "weaknesses": list(inst.persona.weaknesses),
                "status": inst.status,
                "position": inst.persona.position,
            })
    return pool
```

- [ ] **Step 2: 编写测试**

在 `tests/test_roster.py` 末尾添加：

```python
def test_get_talent_pool_includes_available_and_dismissed():
    r = make_roster()
    # 初始：袁崇焕 available
    pool = r.get_talent_pool()
    ids = {p["id"] for p in pool}
    assert "yuan" in ids
    assert "later" in ids
    # 招募后 dismiss
    r.recruit("yuan", MockProvider(), era="崇祯1年1月")
    r.dismiss("yuan")
    pool2 = r.get_talent_pool()
    assert any(p["id"] == "yuan" and p["status"] == "dismissed" for p in pool2)


def test_talent_pool_has_gender_and_weaknesses():
    r = make_roster()
    pool = r.get_talent_pool()
    for p in pool:
        assert "gender" in p
        assert "weaknesses" in p
```

- [ ] **Step 3: 运行测试**

Run: `pytest tests/test_roster.py -v`
Expected: 全部通过

- [ ] **Step 4: Commit**

```bash
git add src/recruitment/roster.py tests/test_roster.py
git commit -m "feat: add get_talent_pool to Roster"
```

---

### Task 4: GameEngine 集成 PositionManager + 任命/卸任方法

**Files:**
- Modify: `src/core/game_engine.py`
- Test: `tests/test_turn.py` 或新建 `tests/test_appoint.py`

- [ ] **Step 1: GameEngine.__init__ 中初始化 PositionManager**

在 `src/core/game_engine.py` 的 `__init__` 方法中，在 `self.roster = Roster(config)` 之后添加：

```python
from src.recruitment.positions import PositionManager

# 在 __init__ 中：
self.roster = Roster(config)
self.positions = PositionManager()  # 新增
```

在 `_setup_initial_court` 方法末尾，为开局在朝官员占用对应职务：

```python
def _setup_initial_court(self) -> None:
    """开局内阁 + 占用职务。"""
    # ... 现有代码 ...
    # 开局在朝官员占用对应职务
    for inst in self.roster.active_instances():
        if inst.persona.position:
            pos = self.positions.get_by_name(inst.persona.position)
            if pos is not None:
                try:
                    self.positions.occupy(pos.id, inst.persona.id)
                except ValueError:
                    pass  # 职务已被占用则跳过
```

注意：`inst.persona.position` 存的是职务名称（如"礼部尚书"），通过 `get_by_name` 匹配到对应职务 id 后再调用 `occupy`。

```python
for inst in self.roster.active_instances():
    if inst.persona.position:
        pos = self.positions.get_by_name(inst.persona.position)
        if pos is not None:
            try:
                self.positions.occupy(pos.id, inst.persona.id)
            except ValueError:
                pass
```

- [ ] **Step 2: 添加 appoint_official / dismiss_official / create_position 方法**

在 GameEngine 类中添加：

```python
def appoint_official(self, persona_id: str, position_id: str) -> dict:
    """从人才库任命官员到指定职务。"""
    era = self.state.era_label()
    inst = self.roster.get(persona_id)
    if inst is None:
        return {"ok": False, "error": f"角色 {persona_id} 不存在"}
    if inst.status not in ("available", "dismissed"):
        return {"ok": False, "error": f"{inst.persona.name} 当前状态不可任命"}
    # 检查职务
    pos = self.positions.get_by_id(position_id)
    if pos is None:
        return {"ok": False, "error": f"职务 {position_id} 不存在"}
    if pos.occupied_by is not None:
        return {"ok": False, "error": f"职务 {pos.name} 已被占用"}
    # 招募/重新启用
    if inst.status == "dismissed":
        self.roster.reinstate(persona_id, self.role_llm, era)
    else:
        self.roster.recruit(persona_id, self.role_llm, era)
    # 占用职务
    self.positions.occupy(position_id, persona_id)
    # 更新 persona.position
    inst.persona.position = pos.name
    return {"ok": True, "name": inst.persona.name, "position": pos.name}

def dismiss_official(self, persona_id: str) -> dict:
    """卸任在朝官员。"""
    inst = self.roster.get(persona_id)
    if inst is None:
        return {"ok": False, "error": f"角色 {persona_id} 不存在"}
    if inst.status != "active":
        return {"ok": False, "error": f"{inst.persona.name} 不在朝"}
    # 释放职务
    self.positions.release_by_persona(persona_id)
    # 卸任
    self.roster.dismiss(persona_id)
    return {"ok": True, "name": inst.persona.name}

def create_position(self, name: str, rank: str, scope: str) -> dict:
    """创建自定义职务。"""
    try:
        pos = self.positions.create(name, rank, scope)
        return {"ok": True, "position": pos.to_dict()}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

def get_vacant_positions(self) -> list[dict]:
    """返回所有空缺职务列表。"""
    return [p.to_dict() for p in self.positions.get_vacant()]

def get_position_management(self) -> dict:
    """返回吏部面板全量数据。"""
    active_officials = [
        {
            "id": a.id,
            "name": a.name,
            "position": a.persona.position,
            "gender": a.persona.gender,
        }
        for a in self.roster.active_agents()
    ]
    return {
        "active_officials": active_officials,
        "talent_pool": self.roster.get_talent_pool(),
        "vacant_positions": [p.to_dict() for p in self.positions.get_vacant()],
        "all_positions": [p.to_dict() for p in self.positions.get_all()],
    }
```

- [ ] **Step 3: 存档/读档兼容 positions**

在 `save` 方法中添加 positions 序列化：

```python
def save(self, path: str | Path) -> None:
    data = {
        # ... 现有字段 ...
        "positions": self.positions.to_dict(),
    }
```

在 `load` 方法中添加 positions 反序列化：

```python
# 在 load 方法中，roster 重建之后：
if "positions" in data:
    eng.positions = PositionManager.from_dict(data["positions"])
else:
    eng.positions = PositionManager()  # 旧存档兼容
```

在 `load_from_slot` 方法中做同样处理：

```python
# 在 load_from_slot 中，roster 重建之后：
if "positions" in data:
    self.positions = PositionManager.from_dict(data["positions"])
else:
    self.positions = PositionManager()
```

在 `new_game` 方法中重置 positions：

```python
def new_game(self) -> None:
    # ... 现有代码 ...
    self.positions = PositionManager()
    # ... 然后 _setup_initial_court() 会占用开局职务 ...
```

- [ ] **Step 4: 编写任命/卸任测试**

新建 `tests/test_appoint.py`：

```python
"""测试吏部任命/卸任系统。"""

import pytest

from src.core.game_engine import GameEngine
from src.llm.provider import MockProvider, load_config


@pytest.fixture
def engine():
    cfg = load_config("config.yaml")
    return GameEngine(
        cfg,
        orchestrator_llm=MockProvider(),
        historian_llm=MockProvider(),
        role_llm=MockProvider(),
    )


def test_appoint_available_to_vacant_position(engine):
    """任命 available 历史人物到空缺职务。"""
    # 找一个 available 的角色
    pool = engine.roster.get_talent_pool()
    available = [p for p in pool if p["status"] == "available"]
    assert len(available) > 0
    target = available[0]
    # 找一个空缺职务
    vacant = engine.get_vacant_positions()
    assert len(vacant) > 0
    result = engine.appoint_official(target["id"], vacant[0]["id"])
    assert result["ok"] is True
    assert result["name"] == target["name"]


def test_appoint_to_occupied_raises(engine):
    """任命到已占用职务应拒绝。"""
    # 先任命一个人
    pool = engine.roster.get_talent_pool()
    available = [p for p in pool if p["status"] == "available"]
    vacant = engine.get_vacant_positions()
    engine.appoint_official(available[0]["id"], vacant[0]["id"])
    # 再任命另一个人到同一职务
    available2 = [p for p in engine.roster.get_talent_pool() if p["status"] == "available"]
    if available2:
        result = engine.appoint_official(available2[0]["id"], vacant[0]["id"])
        assert result["ok"] is False
        assert "已被占用" in result["error"]


def test_dismiss_official(engine):
    """卸任在朝官员。"""
    # 先任命
    pool = engine.roster.get_talent_pool()
    available = [p for p in pool if p["status"] == "available"]
    vacant = engine.get_vacant_positions()
    engine.appoint_official(available[0]["id"], vacant[0]["id"])
    # 卸任
    result = engine.dismiss_official(available[0]["id"])
    assert result["ok"] is True
    # 验证职务已释放
    pos = engine.positions.get_by_id(vacant[0]["id"])
    assert pos.occupied_by is None


def test_dismiss_then_reappoint(engine):
    """卸任后重新任命同一人。"""
    pool = engine.roster.get_talent_pool()
    available = [p for p in pool if p["status"] == "available"]
    vacant = engine.get_vacant_positions()
    pid = available[0]["id"]
    pos_id = vacant[0]["id"]
    # 任命 → 卸任 → 再任命
    engine.appoint_official(pid, pos_id)
    engine.dismiss_official(pid)
    result = engine.appoint_official(pid, pos_id)
    assert result["ok"] is True


def test_create_position(engine):
    """创建自定义职务。"""
    result = engine.create_position("东厂提督", "正四品", "掌东厂刑狱侦缉")
    assert result["ok"] is True
    # 验证出现在空缺列表
    vacant = engine.get_vacant_positions()
    assert any(p["name"] == "东厂提督" for p in vacant)


def test_create_duplicate_position(engine):
    """创建重名职务应拒绝。"""
    engine.create_position("东厂提督", "正四品", "掌东厂")
    result = engine.create_position("东厂提督", "从四品", "重复")
    assert result["ok"] is False
    assert "已存在" in result["error"]


def test_get_position_management(engine):
    """吏部面板全量数据。"""
    mgmt = engine.get_position_management()
    assert "active_officials" in mgmt
    assert "talent_pool" in mgmt
    assert "vacant_positions" in mgmt
    assert "all_positions" in mgmt
```

- [ ] **Step 5: 运行测试**

Run: `pytest tests/test_appoint.py -v`
Expected: 全部通过

- [ ] **Step 6: 运行全量测试确保不破坏**

Run: `pytest -v`
Expected: 全部通过

- [ ] **Step 7: Commit**

```bash
git add src/core/game_engine.py tests/test_appoint.py
git commit -m "feat: integrate PositionManager with GameEngine, add appoint/dismiss methods"
```

---

### Task 5: Web 路由 — 新增吏部 API 端点

**Files:**
- Modify: `src/web/routes.py`
- Test: `tests/test_web.py`

- [ ] **Step 1: 添加 5 个新端点**

在 `src/web/routes.py` 末尾（`_sse` 函数之前）添加：

```python
    # ---- 吏部管理 ----
    @app.get("/positions")
    async def get_positions() -> JSONResponse:
        """获取所有职务（含占用状态）。"""
        return JSONResponse({
            "all_positions": [p.to_dict() for p in engine.positions.get_all()],
            "vacant_positions": [p.to_dict() for p in engine.positions.get_vacant()],
        })

    @app.get("/talent_pool")
    async def talent_pool() -> JSONResponse:
        """获取人才库列表。"""
        return JSONResponse({"talent_pool": engine.roster.get_talent_pool()})

    @app.post("/appoint")
    async def appoint_official(persona_id: str = Form(...), position_id: str = Form(...)) -> JSONResponse:
        """任命官员。"""
        result = engine.appoint_official(persona_id, position_id)
        status = 200 if result["ok"] else 400
        return JSONResponse(result, status_code=status)

    @app.post("/dismiss/{persona_id}")
    async def dismiss_official(persona_id: str) -> JSONResponse:
        """卸任官员。"""
        result = engine.dismiss_official(persona_id)
        status = 200 if result["ok"] else 400
        return JSONResponse(result, status_code=status)

    @app.post("/positions/create")
    async def create_position(name: str = Form(...), rank: str = Form(...), scope: str = Form(...)) -> JSONResponse:
        """新建职务。"""
        result = engine.create_position(name, rank, scope)
        status = 200 if result["ok"] else 400
        return JSONResponse(result, status_code=status)
```

- [ ] **Step 2: 添加 Web 测试**

在 `tests/test_web.py` 末尾添加：

```python
def test_positions_endpoint(client):
    r = client.get("/positions")
    assert r.status_code == 200
    data = r.json()
    assert "all_positions" in data
    assert "vacant_positions" in data
    assert len(data["all_positions"]) > 0


def test_talent_pool_endpoint(client):
    r = client.get("/talent_pool")
    assert r.status_code == 200
    data = r.json()
    assert "talent_pool" in data
    assert len(data["talent_pool"]) > 0


def test_appoint_endpoint(client):
    """任命 available 角色到空缺职务。"""
    # 获取人才库和空缺职务
    pool = client.get("/talent_pool").json()["talent_pool"]
    available = [p for p in pool if p["status"] == "available"]
    assert len(available) > 0
    vacant = client.get("/positions").json()["vacant_positions"]
    assert len(vacant) > 0
    # 任命
    r = client.post("/appoint", data={
        "persona_id": available[0]["id"],
        "position_id": vacant[0]["id"],
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_dismiss_endpoint(client):
    """卸任在朝官员。"""
    # 先任命
    pool = client.get("/talent_pool").json()["talent_pool"]
    available = [p for p in pool if p["status"] == "available"]
    vacant = client.get("/positions").json()["vacant_positions"]
    client.post("/appoint", data={"persona_id": available[0]["id"], "position_id": vacant[0]["id"]})
    # 卸任
    r = client.post(f"/dismiss/{available[0]['id']}")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_create_position_endpoint(client):
    r = client.post("/positions/create", data={
        "name": "东厂提督", "rank": "正四品", "scope": "掌东厂刑狱侦缉",
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True
    # 验证出现在空缺列表
    vacant = client.get("/positions").json()["vacant_positions"]
    assert any(p["name"] == "东厂提督" for p in vacant)
```

- [ ] **Step 3: 运行测试**

Run: `pytest tests/test_web.py -v`
Expected: 全部通过

- [ ] **Step 4: 运行全量测试**

Run: `pytest -v`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add src/web/routes.py tests/test_web.py
git commit -m "feat: add appoint/dismiss/position API endpoints"
```

---

### Task 6: 前端吏部面板 UI

**Files:**
- Modify: `src/web/templates/index.html`

- [ ] **Step 1: 在工具栏添加"吏部"按钮**

在 `index.html` 的 toolbar 中添加：

```html
<button onclick="openLibuPanel()">吏部</button>
```

- [ ] **Step 2: 添加吏部面板模态框 HTML**

在存档弹窗之后、对话弹窗之前添加：

```html
  <!-- 吏部管理弹窗 -->
  <div class="modal-overlay" id="libu-modal">
    <div class="modal-box" style="width:800px">
      <div class="modal-header">
        <h3>吏部 · 官员管理</h3>
        <button class="modal-close" onclick="closeModal('libu-modal')">&times;</button>
      </div>
      <div class="modal-body" id="libu-body" style="max-height:65vh;overflow-y:auto">
        <div style="color:var(--muted)">加载中…</div>
      </div>
    </div>
  </div>
```

- [ ] **Step 3: 添加吏部面板渲染和交互 JavaScript**

在 `refreshState` 函数之前添加：

```javascript
    // ---- 吏部管理 ----
    function openLibuPanel() {
      openModal('libu-modal');
      renderLibuPanel();
    }

    async function renderLibuPanel() {
      const body = document.getElementById('libu-body');
      body.innerHTML = '<div style="color:var(--muted)">加载中…</div>';
      try {
        const [posResp, poolResp] = await Promise.all([
          fetch('/positions'),
          fetch('/talent_pool'),
        ]);
        const posData = await posResp.json();
        const poolData = await poolResp.json();
        const vacant = posData.vacant_positions || [];
        const allPos = posData.all_positions || [];
        const pool = poolData.talent_pool || [];

        // 获取在朝官员
        const stateResp = await fetch('/state');
        const stateData = await stateResp.json();
        const activeOfficials = stateData.active_agents || [];

        let html = '';

        // ---- 在朝官员 ----
        html += '<h3 style="margin-top:0">👑 在朝官员</h3>';
        if (activeOfficials.length === 0) {
          html += '<div style="color:var(--muted);font-size:0.85rem;margin-bottom:1rem">朝中无人</div>';
        } else {
          html += '<div style="display:flex;flex-direction:column;gap:4px;margin-bottom:1rem">';
          for (const a of activeOfficials) {
            html += '<div style="display:flex;justify-content:space-between;align-items:center;background:var(--bg);padding:8px 10px;border-radius:6px;border:1px solid var(--border)">';
            html += `<div><strong>${a.name}</strong><span style="color:var(--muted);margin-left:6px;font-size:0.85rem">${a.position || '无职务'}</span></div>`;
            html += `<button onclick="dismissOfficial('${a.id}','${a.name}')" style="background:#fee2e2;border:1px solid #fecaca;border-radius:4px;padding:3px 10px;color:#dc2626;font-size:0.85rem;cursor:pointer">卸任</button>`;
            html += '</div>';
          }
          html += '</div>';
        }

        // ---- 人才库 ----
        html += '<h3>📋 人才库</h3>';
        if (pool.length === 0) {
          html += '<div style="color:var(--muted);font-size:0.85rem;margin-bottom:1rem">人才库为空</div>';
        } else {
          html += '<div style="display:flex;flex-direction:column;gap:4px;margin-bottom:1rem">';
          for (const p of pool) {
            const genderIcon = p.gender === '女' ? '♀' : '♂';
            const skills = p.skills && p.skills.length ? p.skills.join('、') : '无';
            const weaknesses = p.weaknesses && p.weaknesses.length ? p.weaknesses.join('、') : '无';
            const statusLabel = p.status === 'dismissed' ? '（已卸任）' : '';
            html += '<div style="display:flex;justify-content:space-between;align-items:center;background:var(--bg);padding:8px 10px;border-radius:6px;border:1px solid var(--border)">';
            html += `<div><strong>${p.name}</strong> <span style="color:var(--muted);font-size:0.8rem">${genderIcon}</span>${statusLabel}`;
            html += `<div style="font-size:0.8rem;color:var(--muted)">长处: ${skills} | 缺点: ${weaknesses}</div></div>`;
            html += `<button onclick="openAppointDialog('${p.id}','${p.name}')" style="background:#dbeafe;border:1px solid #bfdbfe;border-radius:4px;padding:3px 10px;color:#2563eb;font-size:0.85rem;cursor:pointer">任命</button>`;
            html += '</div>';
          }
          html += '</div>';
        }

        body.innerHTML = html;
      } catch (err) {
        body.innerHTML = `<div style="color:var(--danger)">加载失败：${err}</div>`;
      }
    }

    async function dismissOfficial(personaId, name) {
      if (!confirm(`确定卸任 ${name}？`)) return;
      const r = await fetch('/dismiss/' + personaId, {method:'POST'});
      const data = await r.json();
      if (data.ok) {
        renderLibuPanel();
        refreshState();
      } else {
        alert(data.error || '卸任失败');
      }
    }

    let appointPersonaId = null;
    let appointPersonaName = '';

    async function openAppointDialog(personaId, name) {
      appointPersonaId = personaId;
      appointPersonaName = name;
      // 获取空缺职务
      const r = await fetch('/positions');
      const data = await r.json();
      const vacant = data.vacant_positions || [];
      let html = `<div style="font-weight:600;margin-bottom:12px">任命 — ${name}</div>`;
      if (vacant.length === 0) {
        html += '<div style="color:var(--muted);font-size:0.85rem">暂无空缺职务，可先新建</div>';
      } else {
        html += '<div style="margin-bottom:10px"><div style="font-size:0.85rem;color:var(--muted);margin-bottom:4px">选择职务</div>';
        html += '<select id="appoint-position-select" style="width:100%;padding:6px 8px;border:1px solid var(--border);border-radius:4px;font-size:0.9rem;background:var(--bg);color:var(--text)">';
        html += '<option value="">— 请选择职务 —</option>';
        for (const p of vacant) {
          html += `<option value="${p.id}">${p.name}（${p.rank}，${p.scope}）</option>`;
        }
        html += '</select></div>';
      }
      html += '<div style="text-align:center;margin:8px 0;color:var(--muted);font-size:0.85rem">— 或 —</div>';
      html += '<button onclick="showNewPositionForm()" style="width:100%;padding:6px;border:1px dashed var(--border);border-radius:4px;background:var(--bg);color:var(--muted);font-size:0.85rem;cursor:pointer">+ 新建职务</button>';
      html += '<div id="new-position-form" style="display:none;margin-top:10px;padding:10px;background:var(--bg);border:1px solid var(--border);border-radius:4px">';
      html += '<div style="margin-bottom:6px"><input type="text" id="new-pos-name" placeholder="职务名称" style="width:100%;padding:5px 8px;border:1px solid var(--border);border-radius:4px;font-size:0.85rem;background:var(--bg);color:var(--text);box-sizing:border-box"></div>';
      html += '<div style="margin-bottom:6px"><select id="new-pos-rank" style="width:100%;padding:5px 8px;border:1px solid var(--border);border-radius:4px;font-size:0.85rem;background:var(--bg);color:var(--text)">';
      const ranks = ['正一品','从一品','正二品','从二品','正三品','从三品','正四品','从四品','正五品','从五品','正六品','从六品','正七品','从七品','正八品','从八品','正九品','从九品'];
      for (const r of ranks) html += `<option value="${r}">${r}</option>`;
      html += '</select></div>';
      html += '<div style="margin-bottom:6px"><input type="text" id="new-pos-scope" placeholder="负责范围" style="width:100%;padding:5px 8px;border:1px solid var(--border);border-radius:4px;font-size:0.85rem;background:var(--bg);color:var(--text);box-sizing:border-box"></div>';
      html += '<button onclick="createAndAppoint()" style="width:100%;padding:5px;background:var(--accent);color:var(--bg);border:none;border-radius:4px;cursor:pointer;font-size:0.85rem">创建并任命</button>';
      html += '</div>';
      html += '<div style="display:flex;gap:8px;margin-top:12px">';
      html += '<button onclick="confirmAppoint()" style="flex:1;padding:6px;background:var(--accent);color:var(--bg);border:none;border-radius:4px;cursor:pointer">确认任命</button>';
      html += '<button onclick="closeModal(\'libu-modal\')" style="flex:1;padding:6px;background:var(--bg);border:1px solid var(--border);border-radius:4px;cursor:pointer">取消</button>';
      html += '</div>';

      // 在当前 body 中显示任命弹窗（覆盖内容）
      const body = document.getElementById('libu-body');
      body.innerHTML = html;
    }

    function showNewPositionForm() {
      document.getElementById('new-position-form').style.display = 'block';
    }

    async function confirmAppoint() {
      const select = document.getElementById('appoint-position-select');
      if (!select || !select.value) {
        alert('请选择职务');
        return;
      }
      const r = await fetch('/appoint', {
        method:'POST',
        headers:{'Content-Type':'application/x-www-form-urlencoded'},
        body: 'persona_id=' + encodeURIComponent(appointPersonaId) + '&position_id=' + encodeURIComponent(select.value),
      });
      const data = await r.json();
      if (data.ok) {
        renderLibuPanel();
        refreshState();
      } else {
        alert(data.error || '任命失败');
      }
    }

    async function createAndAppoint() {
      const name = document.getElementById('new-pos-name').value.trim();
      const rank = document.getElementById('new-pos-rank').value;
      const scope = document.getElementById('new-pos-scope').value.trim();
      if (!name) { alert('请输入职务名称'); return; }
      // 先创建职务
      const cr = await fetch('/positions/create', {
        method:'POST',
        headers:{'Content-Type':'application/x-www-form-urlencoded'},
        body: 'name=' + encodeURIComponent(name) + '&rank=' + encodeURIComponent(rank) + '&scope=' + encodeURIComponent(scope),
      });
      const cData = await cr.json();
      if (!cData.ok) { alert(cData.error || '创建职务失败'); return; }
      // 再任命到新职务
      const posId = cData.position.id;
      const r = await fetch('/appoint', {
        method:'POST',
        headers:{'Content-Type':'application/x-www-form-urlencoded'},
        body: 'persona_id=' + encodeURIComponent(appointPersonaId) + '&position_id=' + encodeURIComponent(posId),
      });
      const data = await r.json();
      if (data.ok) {
        renderLibuPanel();
        refreshState();
      } else {
        alert(data.error || '任命失败');
      }
    }
```

- [ ] **Step 4: 科举流入通知**

在科举授官完毕时（`exam_appoint_one` 路由中），在 engine 上标记新人才流入。在 `src/core/game_engine.py` 中添加：

```python
# 在 GameEngine 类中：
talent_pool_notification: str | None = None  # 科举流入通知文本
```

在 `src/web/routes.py` 的 `exam_appoint_one` 中，当所有贡士授官完毕时：

```python
# 在 if not engine._exam_gongshi: 块中
if not engine._exam_gongshi:
    engine._exam_gongshi = None
    engine._exam_rankings = {}
    engine.talent_pool_notification = f"崇祯{year}年殿试已毕，新科进士已流入人才库，可前往吏部任命。"
```

在 `state` 端点中添加通知字段：

```python
snap["talent_pool_notification"] = getattr(engine, "talent_pool_notification", None)
engine.talent_pool_notification = None  # 读取后清除
```

在前端 `refreshState` 中显示通知：

```javascript
// 在 refreshState 末尾添加：
const notification = s.talent_pool_notification;
if (notification) {
  const banner = document.createElement('div');
  banner.style.cssText = 'background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:10px 14px;margin-bottom:10px;display:flex;align-items:center;gap:8px';
  banner.innerHTML = '<span style="font-size:1.2rem">📜</span><span style="color:#1e40af;font-size:0.9rem">' + notification + '</span>';
  const dialog = document.getElementById('dialog');
  dialog.parentNode.insertBefore(banner, dialog);
  setTimeout(() => banner.remove(), 8000);
}
```

- [ ] **Step 5: 运行全量测试**

Run: `pytest -v`
Expected: 全部通过

- [ ] **Step 6: Commit**

```bash
git add src/core/game_engine.py src/web/routes.py src/web/templates/index.html
git commit -m "feat: add libu management panel UI and exam talent pool notification"
```

---

### Task 7: 存档兼容性 — 旧存档无 positions 字段

**Files:**
- Modify: `src/core/game_engine.py`（已在 Task 4 中处理）

已在 Task 4 Step 3 中通过 `if "positions" in data` 判断处理了旧存档兼容。无需额外任务。

---

### Task 8: 最终验证

- [ ] **Step 1: 运行全量测试**

Run: `pytest -v`
Expected: 全部通过

- [ ] **Step 2: 启动服务器手动验证**

Run: `uv run uvicorn src.web.app:app --reload`
验证：
1. 页面加载正常，白色背景
2. 点击"吏部"按钮打开面板
3. 在朝官员列表显示正确
4. 人才库显示 available + dismissed 角色
5. 任命操作正常
6. 卸任操作正常
7. 新建职务正常
8. 存档/读档后职务状态保持

- [ ] **Step 3: 最终提交**

```bash
git add -A
git commit -m "feat: complete libu management system - appoint/dismiss officials, position management, talent pool"
```
