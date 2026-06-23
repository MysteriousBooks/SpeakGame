# 吏部管理：官员任命与卸任系统设计

## 概述

为游戏增加吏部管理面板，使玩家能够直接任命和卸任官员。官员卸任后进入"人才库"，可从人才库中重新任命到空缺职务。同一职务只能由一位官员担任。

## 数据模型变更

### PersonaCard 新增字段

```python
@dataclass
class PersonaCard:
    # ... 现有字段 ...
    gender: str = ""           # 男/女
    weaknesses: list[str] = field(default_factory=list)  # 缺点列表
```

- `gender`：历史人物手动设定，科举进士随机生成
- `weaknesses`：性格缺陷/行为缺点，如"刚愎自用"、"贪墨"、"马虎"等

### CourtPosition — 新数据类

```python
@dataclass
class CourtPosition:
    id: str                    # 唯一标识
    name: str                  # 职务名称，如"兵部尚书"
    rank: str                  # 品级，如"正二品"
    scope: str                 # 负责范围描述
    occupied_by: str | None = None  # 当前持有者 persona_id，None 表示空缺
```

### PositionManager — 新管理类

职责：
- 持有全部 CourtPosition 列表
- 初始化时加载默认职务集（六部九卿 + 历史角色职务 + 科举职务）
- 查询空缺/已占用职务
- 占用/释放职务
- 创建自定义职务
- 序列化/反序列化（存档用）

## 默认职务集

存档初始化时预置以下职务：

| 职务 | 品级 | 范围 | 初始持有者 |
|------|------|------|-----------|
| 吏部尚书 | 正二品 | 掌全国官吏铨选 | 王永光 |
| 户部尚书 | 正二品 | 掌全国财政 | 空缺 |
| 礼部尚书 | 正二品 | 掌礼仪祭祀科举 | 温体仁 |
| 兵部尚书 | 正二品 | 掌全国武官兵籍 | 空缺 |
| 刑部尚书 | 正二品 | 掌全国刑律狱政 | 乔允升 |
| 工部尚书 | 正二品 | 掌全国工程营造 | 刘遵宪 |
| 左都御史 | 正二品 | 掌都察院监察 | 空缺 |
| 内阁大学士 | 正五品 | 参预机务 | 空缺 |
| 司礼监掌印太监 | 正四品 | 掌内廷批红 | 魏忠贤 |
| 辽东巡抚 | 正四品 | 掌辽东军务 | 空缺 |
| 陕西巡抚 | 正四品 | 掌陕西军政 | 空缺 |
| 三边总督 | 正三品 | 掌三边军务 | 空缺 |
| 大名知府 | 正四品 | 掌大名府政务 | 空缺 |
| 兵部侍郎 | 正三品 | 掌兵部事务 | 空缺 |
| 翰林院修撰 | 从六品 | 掌修国史 | 空缺 |
| 翰林院编修 | 正七品 | 掌修国史 | 空缺 |
| 翰林院庶吉士 | 从七品 | 储才学习 | 空缺 |
| 六科给事中 | 从七品 | 监察六部 | 空缺 |
| 监察御史 | 从七品 | 巡按地方 | 空缺 |
| 六部主事 | 正六品 | 各部实务 | 空缺 |
| 知县 | 正七品 | 掌一县民政 | 空缺 |
| 推官 | 从七品 | 府级司法 | 空缺 |

## 后端变更

### Roster 新增方法

```python
def get_talent_pool(self) -> list[dict]:
    """返回人才库列表：available 历史人物 + dismissed 官员。
    每条包含：id, name, gender, skills, weaknesses, status, 曾任职务"""
```

### GameEngine 新增方法

```python
def appoint_official(self, persona_id: str, position_id: str) -> dict:
    """从人才库任命官员到指定职务。
    - 检查 persona 状态（available/dismissed）
    - 检查 position 是否空缺
    - 调用 roster.recruit() 或 roster.reinstate()
    - 占用 position
    - 更新 persona.position
    - 返回任命结果"""

def dismiss_official(self, persona_id: str) -> dict:
    """卸任在朝官员。
    - 检查 persona 状态（active）
    - 调用 roster.dismiss()
    - 释放 position
    - 返回卸任结果"""

def create_position(self, name: str, rank: str, scope: str) -> dict:
    """创建自定义职务，加入空缺列表。"""

def get_vacant_positions(self) -> list[dict]:
    """返回所有空缺职务列表。"""

def get_position_management(self) -> dict:
    """返回吏部面板全量数据：
    {active_officials, talent_pool, vacant_positions, all_positions}"""
```

### Web 路由新增

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/positions` | 获取所有职务（含占用状态） |
| GET | `/talent_pool` | 获取人才库列表 |
| POST | `/appoint` | 任命官员，参数：persona_id, position_id |
| POST | `/dismiss/{persona_id}` | 卸任官员 |
| POST | `/positions/create` | 新建职务，参数：name, rank, scope |

### 存档变更

存档数据新增 `positions` 字段，保存所有 CourtPosition 的序列化状态（含占用关系和自定义职务）。

## 前端变更

### 吏部面板

新增独立管理面板，包含：

**在朝官员列表**：当前 active 官员，每人显示姓名、当前职务、卸任按钮

**人才库列表**：available 历史人物 + dismissed 官员，每人显示：
- 姓名
- 性别（♂/♀）
- 长处（skills）
- 缺点（weaknesses）
- 任命按钮

**任命弹窗**：
- 显示被任命人信息
- 空缺职务下拉列表（含品级和范围描述）
- "新建职务"按钮 → 展开新建表单
- 确认/取消

**新建职务弹窗**：
- 职务名称（文本输入）
- 品级（下拉选择：正一品~从九品）
- 负责范围（文本输入）
- 创建/取消

### 科举流入通知

科举完毕后，在界面顶部显示蓝色提示条：
"📜 崇祯X年殿试已毕，N名新科进士已流入人才库，可前往吏部任命。"

## 状态机流转

```
科举进士 ──→ 人才库(available) ──任命──→ 在朝(active) ──卸任──→ 人才库(dismissed)
历史人物 ──→ 人才库(available) ──任命──→ 在朝(active) ──卸任──→ 人才库(dismissed)
                                                      ↑──重新任命──┘
```

## 约束规则

1. 同一职务只能被一位官员占用
2. 任命时目标职务必须空缺
3. 卸任后职务自动释放为空缺
4. 卸任可以不立即任命继任者
5. 自定义职务名称不可与现有职务重名
6. 人才库中已故角色（dead）不可任命

## 测试要点

1. 任命 available 历史人物到空缺职务
2. 任命 dismissed 官员（重新启用）
3. 任命到已占用职务 → 拒绝
4. 卸任在朝官员 → 职务释放
5. 卸任后重新任命同一人
6. 创建自定义职务 → 出现在空缺列表
7. 创建重名职务 → 拒绝
8. 存档/读档后职务状态保持
9. 科举进士流入人才库
