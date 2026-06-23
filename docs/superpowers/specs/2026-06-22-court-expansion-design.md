# 开局朝臣扩充 + 职务显示 设计文档

## 目标

1. 开局在朝官员从 3 人扩充为 8 人（六部各一人 + 魏忠贤 + 百姓）
2. 每个官员显示职务（如"户部尚书"）
3. 魏忠贤从抽象事件名变为可交互的角色

## 开局在朝名单

| 角色 | 职务 | 派系 | 来源 |
|------|------|------|------|
| 王永光 | 吏部尚书 | 独相派 | 新增 |
| 毕自严 | 户部尚书 | 循吏系 | 已有 |
| 温体仁 | 礼部尚书 | 独相派 | 已有(招募池) |
| 王在晋 | 兵部尚书 | 主守派 | 已有 |
| 乔允升 | 刑部尚书 | 循吏系 | 新增 |
| 刘遵宪 | 工部尚书 | 循吏系 | 新增 |
| 魏忠贤 | 司礼监掌印太监 | 阉党 | 新增 |
| 黎庶 | 百姓 | — | 已有 |

## 改动清单

### 1. PersonaCard 新增 `position` 字段

`src/agents/base_agent.py`:
- `PersonaCard` 新增 `position: str = ""` 字段
- `from_dict()` 解析 `position`
- `to_prompt_card()` 输出职务
- `to_dict()` 序列化 `position`

### 2. 现有角色 YAML 加 position

- `minister_finance.yaml` → `position: 户部尚书`
- `minister_war.yaml` → `position: 兵部尚书`
- `common_people.yaml` → `position: 百姓`
- `historical_figures.yaml` → 各人物加 `position` 字段

### 3. 新增角色到 historical_figures.yaml

添加 4 个新角色，均标记 `recruitment_condition: 开局在朝`：
- 王永光（吏部尚书）
- 乔允升（刑部尚书）
- 刘遵宪（工部尚书）
- 魏忠贤（司礼监掌印太监）

### 4. 开局激活逻辑修改

`src/core/game_engine.py`:
- `_setup_initial_court()` 改为激活所有 `recruitment_condition == "开局在朝"` 的角色
- 不再硬编码 `_INITIAL_COURT` 列表

### 5. 前端显示职务

`src/web/templates/index.html`:
- "在朝百官"列表显示：`魏忠贤（司礼监掌印太监）`
- 对话弹窗标题显示：`毕自严 · 户部尚书`
- `state_snapshot()` 返回 `position` 字段

## 测试

- 验证开局 8 人全部 active
- 验证每个角色有正确的 position
- 验证魏忠贤可对话
