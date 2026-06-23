# 对话诏书提取与回合流程重设计

## 概述

在明朝社会模拟游戏中，玩家与官员的私下面谈（召见密谈）中，官员会提出政策建议、举荐人才或弹劾同僚。本设计实现从对话中自动提取这些内容作为诏书，并在回合推演中执行（含人事任免更新官职），同时将早朝后置为推演结果的反应环节。

## 回合流程

```
① 玩家与官员对话（召见密谈）
   ↓
② 点击"下一回合"
   ↓
③ 系统扫描当前回合所有对话记录 → LLM 提取建议
   ↓
④ 弹出"对话建议确认"面板
   - 政策建议（默认勾选）
   - 人事任免（默认不勾选，需玩家主动同意）
   ↓
⑤ 玩家确认 → 选中的内容写入待颁诏令列表
   ↓
⑥ 再次点击"下一回合" → 执行推演
   - 编排解析诏书（含任免识别）
   - 执行任免 → 更新官职
   - 史官推演 → 数值变化
   ↓
⑦ 推演结果展示
   ↓
⑧ 早朝开始（百官对结果议政）→ 玩家可插话 → 自然结束
```

## 技术设计

### 1. LLM 提取（GameEngine.extract_edicts_from_dialogues）

**输入：** 当前回合所有官员的对话记录（`DialogueMemory.exchanges`，按 `turn == current_turn` 过滤）

**输出：** 结构化提取结果

```python
@dataclass
class ExtractedSuggestion:
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
    policy_suggestions: list[ExtractedSuggestion]
    personnel_suggestions: list[ExtractedSuggestion]
```

**LLM Prompt 设计：**
- 输入：当前回合对话记录列表
- 输出：JSON 格式的政策建议和人事任免建议
- 提取规则：
  - 政策建议：官员提出的治国方略、财政调整、军事行动等
  - 人事任免：官员举荐他人任职、弹劾他人罢免等
  - 忽略：寒暄、无关话题、已执行的建议

### 2. 编排 agent 扩展（TurnOrchestrator）

在 `ORCHESTRATOR_SCHEMA` 中新增：

```python
# 新增 action 枚举值
"appoint"

# 新增字段
"appointments": {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "person_name": {"type": "string"},
            "position_name": {"type": "string"},
            "action": {"type": "string", "enum": ["appoint", "dismiss"]},
        }
    }
}
```

`OrchestratorPlan` 新增：
- `action == "appoint"` 判断
- `appointments: list[dict]` 字段

### 3. 游戏引擎执行任免（GameEngine）

在 `_run_post_court()` 中新增任免执行逻辑：

```python
# 执行任免
for apt in plan.appointments:
    if apt["action"] == "appoint":
        # 在人才库/在朝官员中查找目标
        target = self.roster.find_by_name(apt["person_name"])
        if target:
            self.appoint_official(target.id, position_id)
    elif apt["action"] == "dismiss":
        target = self.roster.find_by_name(apt["person_name"])
        if target:
            self.dismiss_official(target.id)
```

### 4. 路由层修改（routes.py）

**`/next_turn` 改为两步流程：**

第一步（提取）：
- `POST /next_turn` 带参数 `action=extract`
- 扫描当前回合对话，调用 LLM 提取
- 返回提取结果列表

第二步（执行）：
- `POST /next_turn` 带参数 `action=execute` + 确认后的诏书文本
- 执行推演（编排 → 执行 → 史官）
- 返回推演结果（SSE 流）

**新增 `/court/start`：**
- 推演完成后调用，启动早朝
- 百官对推演结果进行议政
- SSE 流式返回发言

### 5. 前端改动（index.html）

**新增"对话建议确认"模态框：**
- 分两栏展示：政策建议（默认勾选）、人事任免（默认不勾选）
- 每条建议显示来源官员和内容摘要
- "确认采纳"按钮将选中内容写入待颁列表
- "全部忽略"按钮跳过所有建议

**修改"下一回合"交互：**
- 第一次点击：触发提取 → 显示确认模态框
- 确认后：内容写入待颁列表
- 第二次点击：触发执行推演
- 推演完成后：自动进入早朝

**新增早朝后置面板：**
- 推演结果展示完成后，自动显示早朝面板
- 百官发言基于推演结果（而非空谈）
- 玩家可插话
- 早朝自然结束

## 涉及修改的文件

| 文件 | 改动说明 |
|------|----------|
| `src/core/game_engine.py` | 新增 `extract_edicts_from_dialogues()` + 任免执行逻辑 |
| `src/core/turn_orchestrator.py` | 新增 `appoint` action + `appointments` 字段 |
| `src/web/routes.py` | 修改 `/next_turn` 为两步流程 + 新增 `/court/start` |
| `src/web/templates/index.html` | 新增确认模态框 + 两步交互 + 早朝后置 |

## 数据流

```
对话记录 → LLM 提取 → 结构化建议 → 玩家确认 → 待颁列表
                                                      ↓
诏书文本 + 结构化任免数据 → 编排解析 → 执行任免 → 史官推演
                                                      ↓
                                              推演结果 → 早朝议政
```
