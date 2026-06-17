# 技术设计文档：崇祯式 AI 原生历史策略文字游戏

> 多 Agent 社会模拟 · Python + FastAPI Web 应用 · 轻状态层 + 两层记忆 + 信息隔离

## 0. 文档信息

- **目的**：为开发实施提供完整技术规格——数据模型、模块接口、关键流程、提示词/Schema、配置、测试。可直接指导 M0→M4 编码。
- **读者**：本项目开发者（Python 后端 + 前端）。
- **上游**：项目计划 `dreamy-drifting-starlight.md`（决策依据与玩法设计）。本文档聚焦"如何实现"，不重复"为什么"。
- **术语**：
  - **角色 agent**：有人格卡 + 两层记忆 + 信息隔离的 agent（户部尚书/兵部尚书/百姓/招募人物/科举进士）
  - **系统 agent**：功能性 prompt、无人格卡、无信息隔离约束的 agent（编排 Orchestrator / 史官 Historian）
  - **轻状态层**：全局数值由代码持有为 ground truth，史官只推演结构化 delta，代码校验落库
  - **公开层 / 私密层**：agent 输出的两层——公开层可被其他 agent/史官读取，私密层仅自身与玩家（密奏）可见
  - **主线史实事件 / 支线涌现事件**：前者预定义、按史实时间线触发；后者由史官建议、按数值阈值动态触发；两者都经代码数值判定解决

---

## 1. 系统总览

### 1.1 设计目标与约束
- 玩家扮演崇祯，自然语言下诏 → 多 agent 信息隔离执行 → 史官推演数值 delta → 代码校验落库 → 触发新历史事件 → 循环
- 从崇祯元年正月开局，按可调回合长度（周/半月/月）推进时间
- 起步 MVP：3 角色 agent（户部尚书、兵部尚书、百姓）+ 2 系统 agent（编排、史官）

### 1.2 架构分层
```
Web UI (浏览器, SSE 流式)
  早朝群聊 / 召见·求见对话 / 下诏 / 国势面板
        │ HTTP/SSE
        ▼
FastAPI 后端
  系统层  编排 Orchestrator（解析诏书/主持早朝）、史官 Historian（推演delta/财政结算/叙事/预兆/求见汇总）
  交互层  早朝群聊 court_session、求见队列 audience、任务系统 tasks、事件预兆 event_engine
  角色层  Agent 层（户部/兵部/百姓/招募/科举，人格卡+两层记忆+公开私密层）、招募/科举 roster/exam、死亡/处置 lifespan
  数据层  状态层 world_state、财政系统 economy、两层记忆 memory、LLM 接入 provider
```

### 1.3 技术栈
| 组件 | 选型 | 备注 |
|------|------|------|
| 语言 | Python ≥ 3.11 | async/await |
| 后端 | FastAPI + uvicorn | 原生 async/SSE |
| 前端 | HTMX + Jinja2（MVP）→ React+Vite（成熟后） | 零构建工具起步 |
| LLM 接入 | httpx 直连各家 API | DeepSeek/Qwen（OpenAI 兼容）/ Claude（Anthropic）/ Mock |
| 编排 | 纯手写 asyncio | LangGraph 留作后期评估 |
| 状态存储 | JSON 文件（MVP） | SQLite 留作数据量增大后 |
| 并发 | asyncio.gather | 多 agent 并行推演 |
| 模型策略 | 双模型：编排/史官用强模型，角色 agent 用低成本模型 | 控成本 |
| 包管理 | uv | |

### 1.4 核心设计原则
1. **轻状态层**：全局数值代码持有 ground truth；LLM 只产出结构化 delta；代码校验（边界/幅度）后落库。数值不靠 LLM 主观维护。
2. **代码管数值，LLM 管叙事**：确定性逻辑（财政结算、事件解决判定、delta 校验）用代码；开放叙事（大臣对话、事件描写、预兆）用 LLM。
3. **信息隔离**：角色 agent 之间不共享私密层；早朝只共享公开层；史实死因/正反派等元数据不注入 agent 提示词。
4. **每回合无状态加载**：agent 每回合新 session，加载压缩后的两层记忆；不依赖跨回合上下文累积。
5. **事件驱动激活**：编排只激活与当前诏书/议题相关的 agent 子集，控制成本（非 O(N²) 全连接）。

---

## 2. 核心数据模型

### 2.1 WorldState（世界状态 ground truth）
```python
# src/core/world_state.py
from dataclasses import dataclass, field

@dataclass
class WorldState:
    era: str = "崇祯"
    year: int = 1            # 崇祯元年
    month: int = 1
    day: int = 1              # 按 turn_length 推进；累计到新月则 year/month 更新
    # 全局数值（受 bounds 约束，delta 代码校验）
    values: dict = field(default_factory=lambda: {
        "国库": 1_000_000,     # 太仓
        "内帑": 5_000_000,
        "民心": 55, "军力": 60, "军心": 55,
        "朝堂清洗度": 10,       # 铲除魏忠贤用
        "宗室不满": 20,
        "陕西_民心": 30, "京畿_民心": 50,
        "陕西_人口": 5_000_000,
    })
    active_events: list = field(default_factory=list)   # 活跃事件 id
    resolved_events: list = field(default_factory=list)
    active_tasks: list = field(default_factory=list)    # 进行中任务

    def snapshot(self) -> dict: ...          # 供史官读取的只读数值快照
    def get(self, key) -> float: ...
    def validate_delta(self, delta: dict, bounds: dict) -> tuple[dict, list[str]]: ...  # 返回 (裁剪后实际delta, 错误信息)
    def apply(self, applied_delta: dict): ...# 落库
    def advance(self, turn_length: str): ... # 按 turn_length 推进 day，跨月则更新 year/month
    def save(self, path): ...
    @classmethod
    def load(cls, path) -> "WorldState": ...
```

**delta 校验规则**（`validate_delta`）：
- 未知数值键 → 报错忽略（防 LLM 凭空捏造）
- 变更超 `max_delta` → 裁剪到 ±max_delta
- 新值越 `min/max` → 裁剪到边界，记录实际 delta
- 返回错误列表供史官重推参考

### 2.2 数值 bounds（config.yaml）
```yaml
bounds:
  国库: {min: 0, max: 10000000, max_delta: 500000}
  内帑: {min: 0, max: 10000000, max_delta: 1000000}
  民心: {min: 0, max: 100, max_delta: 30}
  军力: {min: 0, max: 100, max_delta: 20}
  军心: {min: 0, max: 100, max_delta: 25}
  朝堂清洗度: {min: 0, max: 100, max_delta: 40}
  宗室不满: {min: 0, max: 100, max_delta: 30}
  陕西_民心: {min: 0, max: 100, max_delta: 30}
  京畿_民心: {min: 0, max: 100, max_delta: 30}
  陕西_人口: {min: 0, max: 10000000, max_delta: 500000}
```

### 2.3 角色卡与状态机
```python
# 角色状态机：available → active ↔ dismissed → dead
ROLES = ["available", "active", "dismissed", "dead"]
# available/dismissed 可招募为 active；dismissed 复用带历史记忆与怨气；dead 不可复活
```

**历史角色卡**（`agents/personas/historical_figures.yaml`）：
```yaml
- id: yuan_chonghuan
  name: 袁崇焕
  courtesy: 元素
  born_year: 1584
  historical_death_year: 1630
  death_cause: {type: execution, desc: 崇祯三年被凌迟}
  faction: 辽东系
  skills: [军事, 辽防, 守城]
  historical_alignment: 争议      # 正派|反派|中性|争议（仅 easy 难度可见）
  personality: 刚烈敢言、自负
  relations: {政敌: 阉党余孽}
  recruitment_condition: 辽东局势紧张时可召
  per_agent: {忠诚: 70, 不满: 0, 安全度: 50}   # per-agent 属性初值
```

**科举进士人格卡**（运行时由答卷/背景生成，无史实元数据）：
```python
# 字段同上但 historical_death_year/death_cause/historical_alignment 缺省
# 自然死亡按 average_lifespan 计算
```

**MVP 开局内阁 persona 文件**：`minister_finance.yaml`（户部尚书）、`minister_war.yaml`（兵部尚书）、`common_people.yaml`（百姓 agent）。

### 2.4 事件结构

**主线史实事件**（`events/historical_events.yaml`）：
```yaml
- id: ji_si_zhi_bian
  name: 己巳之变
  trigger_time: 崇祯2年10月          # 史实触发时间
  premonition_lead: 3                # 提前 3 个月出现预兆（单位=月）
  background: 皇太极率后金军绕道蒙古入塞，直逼京畿...
  involved_agents: [兵部尚书, 百姓_京畿]
  task_desc: 后金军入塞，京畿危急，须调兵勤王、筹措军饷
  resolve_conditions:               # 数值阈值，代码判定
    军力: ">=70"
    国库: ">=200000"
    京畿_民心: ">=50"
  fail_consequences:
    - 逾月不解决则军力-15、京畿_民心-20、可能触发"京畿沦陷"
```

**支线涌现事件**（史官输出 `new_events`，基于数值阈值动态触发）：
```json
{"type": "民变", "province": "陕西", "trigger_condition": "陕西_民心<20", "resolve_conditions": {...}}
```

**角色级死亡危机事件**（按角色 `historical_death_year` 触发，复用 event_engine 的数值判定逻辑）：
```yaml
resolve_conditions: {安全度: ">=80", 皇帝未得罪其政敌: true}  # per-agent 安全度
```

### 2.5 任务对象
```python
# src/core/tasks.py
@dataclass
class Task:
    task_id: str
    target_agent: str           # 目标角色 agent_id
    task: str                   # 任务内容
    affects: list[str]          # 影响数值键
    deadline: str               # 期限（崇祯X年X月）
    success_condition: str      # 成功条件
    status: str = "pending"     # pending|in_progress|done|failed|overdue
    progress: float = 0.0       # 史官每回合推演进度
```

### 2.6 财政数据
```python
# src/finance/economy.py
@dataclass
class FinanceState:
    treasury: int = 1_000_000       # 太仓国库
    inner_purse: int = 5_000_000     # 内帑
    income_monthly: dict = {田赋: 220000, 商税: 40000, 辽饷加派: 90000, 其他: 10000}
    expense_monthly: dict = {辽东军饷: 150000, 边镇京营: 80000, 宗室岁禄: 90000, 官俸: 25000, 其他: 15000}
    tax_rates: dict = {田赋率: 0.05, 辽饷加派率: 0.03, 商税率: 0.02}
    zonglu_reform: dict = {}        # 宗禄改革参数（削减比例/折钞率等）
    temp_expense: list = []        # 本月额外临时支出（赈灾/军需/赏赐/工程）

    def settle(self, year景: str, war_factor: float, rebellion_factor: float) -> dict:
        """每回合财政结算。返回 {收入: ..., 支出: ..., 净: ..., delta: {国库: 净}}。
        年景调制田赋、战事调制军饷、民变中断地方税收。"""
    def transfer_inner_to_treasury(self, amount) -> bool: ...   # 内帑→太仓（允许）
    def transfer_treasury_to_inner(self, amount) -> bool: ...  # 太仓→内帑（禁止，返回 False）
```

**支出多维度分类**：按用途/对象/性质（固定 vs 临时）/刚性（祖制刚性 vs 可调节）。

### 2.7 两层记忆
```python
# 事实记忆：结构化条目，按 tag 检索，不压缩，全保留
@dataclass
class FactualNote:
    note_id: str
    agent_id: str
    content: str          # 如"崇祯三年春，帝拨银十万赈陕西"
    tags: list[str]        # [陕西, 赈灾, 崇祯3年] 检索用
    importance: int        # 重要度
    timestamp: str

# 叙事记忆：压缩的自然语言印象，持久化到文件，每回合加载
@dataclass
class NarrativeMemory:
    agent_id: str
    summary: str           # 压缩后的主观印象
    updated_at: str
```

**加载策略**：每回合 agent 加载 = 角色卡 + 相关事实记忆（按 tag 过滤，非向量 RAG）+ 压缩叙事记忆。

---

## 3. 模块详细设计

| 模块 | 职责 | 关键接口 |
|------|------|---------|
| `core/world_state.py` | 全局数值 ground truth + delta 校验 + 时间推进 | `snapshot/validate_delta/apply/advance/save/load` |
| `core/turn_orchestrator.py` | 编排 agent：解析诏书→分类→分派/处置 | `parse_edict(edict, state) -> EdictPlan`、`run_court(state, agents)` |
| `core/historian.py` | 史官 agent：推演 delta + 财政结算 + 叙事 + 预兆 + 求见汇总 | `run(state, agent_outputs, edict, upcoming_events) -> HistorianOutput` |
| `core/audience.py` | 求见队列管理：汇总 want_audience → 玩家见/不见 + 后果 | `build_queue(agent_outputs) -> [AudienceReq]`、`grant/deny(req)` |
| `core/court_session.py` | 早朝群聊：共享公开上下文 + 请奏 + 论辩 + 玩家介入 | `run(state, active_agents, topic) -> CourtLog` |
| `core/tasks.py` | 任务系统：诏书→任务对象 + 进度跟踪 + 结算 | `create_from_edict/progress/update_status` |
| `finance/economy.py` | 财政系统：太仓/内帑分库 + 支出分类 + 宗禄改革 + 结算 | `settle/transfer_*/apply_zonglu_reform` |
| `agents/base_agent.py` | 角色 agent 基类：人格卡 + 两层记忆 + 公开私密层 + 求见意愿 | `speak/visit/respond/produce_want_audience` |
| `recruitment/roster.py` | 角色库加载 + 按年份过滤在世可招募 + 状态机 | `load_roster/filter_alive/recruit/set_status` |
| `recruitment/lifespan.py` | 平均寿命/自然死亡 + 死亡危机事件 + 赐死/免职后果 | `trigger_death_crisis/resolve_to_natural/execute/dismiss` |
| `recruitment/exam.py` | 科举三级 + 殿试授官 + 进士人格生成 | `run_exam/present_gongshi/appoint` |
| `memory/factual_memory.py` | 事实记忆：结构化条目 + tag 检索 + 持久化 | `add/query_by_tags/save/load` |
| `memory/narrative_memory.py` | 叙事记忆：压缩 + 持久化 + 每回合加载 | `compress/load/save` |
| `llm/provider.py` | LLM 多模型抽象 + Key 管理 + 流式 + Mock | `get_provider/chat/stream` |
| `events/event_engine.py` | 事件预兆 + 按史实时间线触发 + 数值阈值判定解决 | `due_events/check_resolutions/apply_fail_consequences` |
| `web/app.py` | FastAPI 入口 | lifespan + 路由注册 |
| `web/routes.py` | 下诏/召见/国势接口（SSE 流式） | `POST /edict`、`POST /audience/{id}`、`GET /state`（SSE） |

**编排 vs 史官 分工**：编排 = 路由层（解析诏书→分类→分派/处置/识别类型，不推演数值）；史官 = 推演层（推演 delta + 财政结算 + 叙事 + 触发事件 + 汇总求见 + 生成预兆，不解析分派）。

---

## 4. 关键流程

### 4.1 回合主流程（伪代码）
```
每回合：
  1. 开局奏报：
     - event_engine.due_events(state) → 触发到期主线史实事件挂起
     - historian 生成预兆（即将触发事件，premonition_lead 月内）
     - audience.build_queue(上回合 agent_outputs) → 求见队列（仅主题）
  2. 早朝 court_session.run(state, active_agents, current_topics):
     - 开场呈上（局势/预兆/求见主题）
     - 按议题事件驱动激活相关 agent 子集发言（公开层）
     - agent 间论辩（派系附和/攻讦，公开层）
     - 玩家质询/下政令（早朝是下诏入口）
  3. 玩家可单独召见求见者（一对一密奏，私密层可吐露）
  4. 玩家下诏（召见/求见/早朝质询中）：
     - orchestrator.parse_edict → EdictPlan
       * 皇权处置识别（赐死/免职）→ lifespan 直接处置
       * 财政划拨识别（内帑→国库 允许；反向 拒绝）
       * 宗禄改革识别 → economy.apply_zonglu_reform
       * 普通政令 → tasks.create_from_edict（派任务给目标角色）
     - 编排只激活相关 agent 子集执行（信息隔离）
  5. agent 执行（并行 asyncio.gather）：
     - 各 agent 产出 public/private + want_audience + 执行结果
  6. historian.run(state, agent_public_outputs, edict, upcoming_events):
     - 推演 delta（财政/军事/民政/人事类政令效果）
     - 财政结算 economy.settle（年景/战事/民变调制）
     - 生成叙事 + 支线涌现事件建议（new_events）
     - 生成下回合预兆 + 汇总求见队列
  7. 代码校验落库：
     - world_state.validate_delta(historian.delta, bounds) → 裁剪 + 错误
     - 校验失败 → 史官重推（≤3 次），仍失败用默认值兜底
     - world_state.apply(applied_delta)
  8. 代码判定事件解决：
     - event_engine.check_resolutions(state) → 解决/挂起
     - apply_fail_consequences（未解决事件恶化）
     - 死亡危机事件同判定（角色安全度阈值）
  9. 时间推进：state.advance(turn_length) → 跨月触发该月史实事件
  10. 持久化：world_state.save + 各 agent 记忆快照（存档）
  → 下一回合
```

### 4.2 下诏即派任务流程
```
玩家在对话中下诏 "清查各省欠赋"
→ orchestrator.parse_edict:
   识别为财政类任务 → tasks.create_from_edict(target=户部尚书, affects=[田赋,国库], deadline=崇祯1年6月)
→ 户部尚书 agent 执行（基于人格/记忆/当前局势，信息隔离）
→ historian 推演任务进度 + delta（田赋↑、国库↑）
→ 代码校验落库 + 任务进度更新
跨回合执行至 deadline，达成 success_condition → done；否则 failed/overdue
```

### 4.3 死亡避免流程
```
推进至角色 historical_death_year 附近 + 死因非自然
→ lifespan.trigger_death_crisis(角色) → 死亡危机事件挂起（resolve_conditions=角色安全度阈值）
玩家路径 A（化解）：与角色交谈/下诏保护 → 角色安全度↑ → 达成 resolve_conditions → 事件解决 → 角色转自然死亡（按 average_lifespan 重算）
玩家路径 B（不干预）：未化解 → 角色按史实非自然死亡 → agent 移除 → 触发后续事件（如辽东军心震动）
玩家路径 C（皇权处置）：下诏"赐死" → orchestrator 识别 → lifespan.execute → 直接 dead（绕过死亡危机）→ 后果 delta
```

### 4.4 科举流程
```
推进至科举年（exam_cycle_years=3）→ 预兆（礼部奏请开科）
→ exam.run_exam: 乡试（生成各省举人）→ 会试（筛贡士）→ 殿试
→ 殿试 present_gongshi：呈现贡士信息（按难度控制可见性）
→ 玩家定名次 + 授官
→ exam.appoint：生成进士人格卡 → roster.set_status(进士, active) → 新增 agent 入在朝池
```

### 4.5 财政结算流程
```
economy.settle(年景, war_factor, rebellion_factor):
  实际收入 = base_income × 年景系数 + 加派(税率×税基) - 民变中断税收
  实际支出 = base_expense × war_factor + 宗室岁禄(受改革参数调制) + temp_expense
  净 = 收入 - 支出
  delta = {国库: 净}
→ 与史官政令效果 delta 合并 → world_state.validate_delta → apply
```

---

## 5. 提示词与输出 Schema 规格

### 5.1 编排 agent（`prompts/orchestrator.md`）
```
角色：皇帝诏书的"中书省"，把自然语言诏书拆解为可执行分派指令。
输入：诏书文本 + 当前回合号 + 可用 agent 列表
输出 JSON：{type: "task|execute|dismiss|finance_transfer|zonglu_reform", target_agent, ...}
约束：
- 只激活与本诏书相关的 agent 子集（成本控制），禁止无目的的全员拜访
- 皇权处置识别："赐死/免职 X" → {type: execute/dismiss, target}，不经死亡危机 resolve
- 财政划拨识别："动用内帑充国库" → 允许内帑→国库；"挪国库入内帑" → 拒绝"公帑不可入私库"
- 任务解析：普通政令 → 任务对象（目标角色/影响数值/期限/成功条件）
```

### 5.2 史官 agent（`prompts/historian.md`）
```
角色：世界的"推演引擎+起居注官"
输入：各 agent 公开层输出 + 世界数值快照 + 财政参数快照 + 诏书 + 即将触发事件列表(含预兆阶段)
输出 JSON（强制 schema，delta_schema.json）：
  {narrative, delta, new_events, factual_notes, audience_queue}
约束：
- delta 可被代码校验（数值范围/幅度）；数值变更要有叙事因果
- 历史/性格 grounding 硬约束：基于当前时间点史实背景与明末时代边界，不得超越明末（禁止"崇祯元年造原子弹"等脱离时代的行为）；结果须能用当时历史条件+人物性格解释
- 事件解决由代码按数值阈值判定，史官只推演 delta
- 财政政令处理/宗禄改革识别/临时支出处理/预兆生成/求见汇总
- guided thinking：先回答"诏书可行吗？需多少资源？各省民心如何变化？"再输出 delta
```

### 5.3 角色 agent 通用（`prompts/agent_base.md` + 角色卡）
```
加载：角色卡（人格/派系/关系网/立场）+ 相关事实记忆（按 tag 过滤）+ 压缩叙事记忆
信息隔离硬约束："你不知道其他官员的私下立场，只能看到公开的军情/灾情/表态。你的真实立场属私密层，仅在玩家密奏或必要时吐露。"
输出 JSON：{public: 公开表态/执行结果, private: 内心真实想法(仅自己/密奏可见), want_audience: bool, audience_topic: 模糊主题}
拜访接口：接收对方 public 层作为输入，产出自己的 public/private
性格与历史驱动：符合角色卡性格与当前史实处境，不超越该历史节点合理行为范围
元信息隔离：史实死因/正反派等元数据不注入提示词，agent 不预知自己未来命运
```

### 5.4 早朝场景（`prompts/court.md`）
```
多 agent 共享公开上下文的群聊：每个在朝 agent 看到朝堂所有公开发言（公开层），看不到其他 agent 私密层
发言基于：自身人格卡 + 相关事实记忆 + 当前早朝公开对话历史 + 当前局势/事件
发言约束：只输出公开层表态（请奏/附和/论辩/攻讦），不泄露自己或他人私密立场；符合人格与派系立场
输出 JSON：{public: 朝堂发言, to: 可选论辩对象, stance: 立场表态, want_audience, audience_topic}
群聊上下文由编排注入（累积公开发言历史，裁剪控长）
```

### 5.5 殿试场景（`prompts/exam.md`）
```
玩家直接交互节点：呈现所有贡士信息，玩家定名次授官
信息可见性按全局难度：easy 显示能力倾向、normal 仅答卷+籍贯、hard 仅答卷
授官后生成进士人格卡（籍贯/答卷风格→性格倾向/擅长/立场初值）→ 新 agent
不涉及数值 delta，是 agent 输入通道
```

### 5.6 delta_schema.json
```json
{
  "type": "object",
  "required": ["narrative", "delta", "new_events", "factual_notes", "audience_queue"],
  "properties": {
    "narrative": {"type": "string"},
    "delta": {"type": "object", "additionalProperties": {"type": "number"}},
    "new_events": {"type": "array", "items": {"type": "object"}},
    "factual_notes": {"type": "array", "items": {"type": "string"}},
    "audience_queue": {"type": "array", "items": {"type": "object",
      "properties": {"agent_id": {"type":"string"}, "topic":{"type":"string"}, "urgency":{"type":"string"}}}}
  }
}
```

---

## 6. 配置规格（config.yaml，M0 重建）

```yaml
game:
  era_name: 崇祯
  start_year: 1
  start_month: 1
  turn_length: month          # week | half_month | month
  difficulty: normal          # easy | normal | hard（全局，控制招募/殿试信息可见性）
  average_lifespan: 50        # 自然死亡平均寿命（岁）
  exam_cycle_years: 3         # 科举周期（明制 3，可改 1）

llm:
  default_provider: mock      # mock | deepseek | qwen | claude
  orchestrator: {provider: claude, model: claude-opus-4-8}
  historian: {provider: claude, model: claude-opus-4-8}
  role_agent: {provider: deepseek, model: deepseek-chat}

bounds:                        # 数值边界 + 单回合 max_delta
  国库: {min: 0, max: 10000000, max_delta: 500000}
  内帑: {min: 0, max: 10000000, max_delta: 1000000}
  民心: {min: 0, max: 100, max_delta: 30}
  军力: {min: 0, max: 100, max_delta: 20}
  军心: {min: 0, max: 100, max_delta: 25}
  朝堂清洗度: {min: 0, max: 100, max_delta: 40}
  宗室不满: {min: 0, max: 100, max_delta: 30}
  陕西_民心: {min: 0, max: 100, max_delta: 30}
  京畿_民心: {min: 0, max: 100, max_delta: 30}
  陕西_人口: {min: 0, max: 10000000, max_delta: 500000}

turn:
  max_retries: 3               # 史官 delta 校验失败重试

finance_initial:
  treasury: 1000000
  inner_purse: 5000000
  income_monthly: {田赋: 220000, 商税: 40000, 辽饷加派: 90000, 其他: 10000}
  expense_monthly: {辽东军饷: 150000, 边镇京营: 80000, 宗室岁禄: 90000, 官俸: 25000, 其他: 15000}
  tax_rates: {田赋率: 0.05, 辽饷加派率: 0.03, 商税率: 0.02}
```

---

## 7. 数据文件规格

- `agents/personas/historical_figures.yaml`：真实历史角色库（字段见 §2.3）
- `agents/personas/minister_finance.yaml` / `minister_war.yaml` / `common_people.yaml`：开局内阁 persona
- `events/historical_events.yaml`：主线史实事件库（字段见 §2.4）
- `.env`（从 `.env.example` 复制）：`DEEPSEEK_API_KEY` / `DASHSCOPE_API_KEY` / `ANTHROPIC_API_KEY` / `LLM_PROVIDER`
- `saves/{slot}/`：存档目录 = world_state.json + 各 agent 记忆快照 + 活跃事件/任务状态 + 财政参数

---

## 8. LLM Provider 接口规格

```python
# src/llm/provider.py
class LLMProvider(ABC):
    async def chat(self, messages: list[dict], *, temperature=0.7,
                   max_tokens=1024, response_format=None) -> str: ...
    async def stream(self, messages: list[dict], *, temperature=0.7,
                     max_tokens=1024) -> AsyncIterator[str]: ...

class OpenAICompatProvider(LLMProvider): ...   # DeepSeek/Qwen（OpenAI 兼容）
class ClaudeProvider(LLMProvider): ...          # Anthropic（system 单独传）
class MockProvider(LLMProvider): ...             # 无 Key 确定性占位响应

def get_provider(provider: str, model: str) -> LLMProvider: ...
```

**双模型路由**：编排/史官用强模型（Claude/Qwen-Plus），角色 agent 用低成本模型（DeepSeek/Qwen-Flash）。
**Mock 范围**：Mock 验证流程骨架与数据流（结构化占位）；真模型验证信息隔离/涌现趣味/推演合理性。
**Key 管理**：`.env` 加载，玩家可自带 Key；开发期用 mock 模式跑通逻辑。

---

## 9. Web 接口规格

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 主界面（早朝/对话/国势面板） |
| GET | `/state` (SSE) | 国势实时推送（数值/事件/预兆/求见队列） |
| POST | `/edict` | 下诏（流式返回编排分派+执行+史官推演叙事） |
| POST | `/audience/{id}` | 处理求见（见/不见，见则进入一对一对话） |
| POST | `/court/speak` | 早朝中玩家插话/质询/下政令 |
| POST | `/recruit/{figure_id}` | 招募历史人物 |
| POST | `/exam/appoint` | 殿试授官 |
| POST | `/save` / `/load` | 存档/读档 |

**前端**：HTMX + Jinja2（MVP）——早朝群聊用 SSE 流式渲染 agent 依次发言；国势面板展示数值/内帑国库/事件/预兆/招募池/科举殿试。

---

## 10. 信息可见性模型

- **公开层**：军情/灾情/公开表态/执行结果/早朝发言——其他 agent 拜访可读、史官可收集
- **私密层**：真实立场/秘密/私下盘算——仅该 agent 自身与玩家（密奏）可见
- **奏折机制**：大臣私密层可"上达天听"（玩家召见时选择性吐露）
- **元信息隔离**：史实死因/正反派等系统元数据**不注入 agent 提示词**，agent 不预知自己未来命运
- **难度等级**（全局）：easy 上帝视角辅助（招募/殿试显示历史信息）；normal 部分显示；hard 零剧透（最沉浸）

---

## 11. 错误处理与数值校验

| 场景 | 处理 |
|------|------|
| 史官 delta 含未知数值键 | 忽略该键，记录错误供史官重推 |
| delta 超 max_delta / 越界 | 代码裁剪到边界，记录实际 delta |
| delta 校验失败 | 带错误信息让史官重推（≤3 次），仍失败用默认值兜底 |
| LLM 输出不符 JSON schema | schema 校验失败重试（≤3 次）+ 兜底默认值 |
| 内帑→国库划拨 | 允许（扣内帑加国库） |
| 国库→内帑划拨 | 拒绝"公帑不可入私库"，强行触发"朝野哗然"事件（民心-/官员忠诚-） |
| 早朝发言泄露私密层 | 提示词硬约束 + 输出只取 public 层 |
| agent 推演延迟 | asyncio 并行 + 流式输出 + 短超时 |

---

## 12. 测试策略

**单元测试**（`pytest tests/`，mock LLM）：
- `test_world_state.py`：delta 校验（幅度裁剪/边界裁剪/未知键忽略）、时间推进（周/半月/月）
- `test_memory.py`：两层记忆读写/按 tag 检索/压缩持久化
- `test_economy.py`：财政结算（年景/战事/民变调制）、内帑单向划拨、宗禄改革减免
- `test_event_engine.py`：按时间线触发、预兆 lead 月判定、纯代码数值阈值解决
- `test_roster.py`：按年份过滤在世可招募、状态机转换
- `test_turn.py`：端到端回合（mock LLM）——下诏→分派→执行→delta→落库→事件解决

**集成/端到端**（接真模型，见 §11 验证 1-19）：
- 核心闭环、事件解决判定、招募、死亡避免、皇权处置、回合长度、财政、预兆、内帑、求见、早朝、下诏派任务、科举、宗禄改革
- 数值稳定性（连续 20 回合无矛盾）、信息隔离（百姓不知户部私密层）、记忆连续性（第 5 回合许诺第 10 回合记得）、成本（<1 元/回合 DeepSeek）
- benchmark：同诏书跑 10 次 delta 一致性 ≥ 80%

**Mock vs 真模型分工**：Mock 验证流程/数据流骨架；真模型验证内容质量/信息隔离/推演合理性。

---

## 13. 里程碑与实施顺序

| 里程碑 | 内容 | 工期 |
|--------|------|------|
| M0 | `uv` 初始化、`llm/provider.py` 多模型抽象（含 Mock）跑通一次对话、`.env` Key 管理、config.yaml 重建 | 1-2 天 |
| M1 | `world_state.py`（数值+delta 校验+时间推进+内帑/国库分库）、`finance/economy.py`（太仓/内帑分库+支出分类+宗禄改革+固定/临时支出+结算+单向划拨）、`factual_memory.py`/`narrative_memory.py`、单元测试 | 4-5 天 |
| M2 | `base_agent.py`（人格卡/公开私密层/拜访/求见意愿）、`historical_figures.yaml`+`roster.py`（按年份过滤+状态机）+`exam.py`（科举三级+殿试授官+进士生成）+`lifespan.py`（死亡危机/自然死亡/赐死免职后果）+`audience.py`（求见队列/见不见后果）+`court_session.py`（早朝群聊）+`tasks.py`（下诏派任务/进度结算）、`orchestrator`+`historian`+提示词、回合长度可调、打通"早朝请奏→下诏派任务→分派/处置→执行→汇总→delta→落库→求见队列"（先 mock 再真模型） | 6-8 天 |
| M3 | `event_engine.py`（预兆+时间线触发+数值阈值判定解决）、FastAPI+SSE 流式、HTMX 前端（对话+国势面板+预兆奏报）、存档/读档 | 2-3 天 |
| M4（可选） | benchmark、缓存、成本统计、扩展更多 agent | - |

---

## 14. 附录

### 14.1 复用的参考实现
- [ming-salvage-sim](https://github.com/wangwei-ying3/ming-salvage-sim)：月度回合制、四维承办人修正、记忆卡按重要度衰减、DeepSeek 85% 缓存命中
- [AIdventure](https://github.com/kagsteiner/aidventure)：双模型架构、故事弧 5 阶段、记忆修剪+总结
- [Intra 设计笔记](https://ianbicking.org/blog/2025/07/intra-llm-text-adventure.html)：代码管 ground truth vs LLM 叙事、guided thinking、inline markup
- [punt-labs/dungeon](https://github.com/punt-labs/dungeon)：markdown 驱动、YAML 存状态
- Stanford Generative Agents：memory stream + observation + reflection + planning
- [llm-adventure](https://github.com/Farsinuce/llm-adventure)：骰子概率 + LLM 叙事分离

### 14.2 关键风险对策（摘要）
数值长局崩→轻状态层+delta校验+guided thinking+benchmark；记忆丢失→两层记忆；Token 成本→事件驱动激活子集+双模型+缓存；agent 串话→公开/私密层+提示词硬约束；LLM 输出不结构化→JSON schema+重试+兜底；脱离时代→时间锚点+明末边界硬约束+人物性格驱动；剧透→元数据不注入提示词+难度控制；死亡计算偏差→平均寿命配置+阶层微调+代码判定；滥用赐死→强后果 delta；财政崩溃→史实开局+代码确定性结算；内帑挪用→单向划拨；宗禄改革→不满后果；求见错失→拒见忠诚-+错过预警；早朝成本→发言轮数+低成本模型；任务漂移→期限+成功条件+max_delta 裁剪；科举膨胀→控数量。

### 14.3 MVP 预留（暂不实现）
军心低兵变机制、宗室不满→宗室动荡事件——MVP 预留，仅数值记录，后果事件后续扩展。