# speakGame — 崇祯式多 Agent 社会模拟

AI 原生历史策略文字对话游戏。玩家扮演崇祯，用自然语言下诏，多 Agent 社会模拟推演后果并修改世界数值，循环产生新危机。

## 核心创新

采用 **多 Agent 社会模拟** 架构——每个重要历史人物是独立 LLM agent，拥有历史人格（性格/派系/关系网），**agent 之间信息不互通**（各有私下盘算），可互相拜访、主动求见，最后由史官汇总全局。对标 Stanford Generative Agents 范式。

## 技术栈

- Python 3.13 + uv
- FastAPI + SSE 流式 + HTMX/Jinja2 前端
- httpx 直连各 LLM（DeepSeek / Qwen / Claude，可切换，mock 兜底）
- asyncio.gather 并行 agent；JSON 文件状态存储（ground truth 由代码持有）

## 快速开始

```bash
uv sync                     # 安装依赖
cp .env.example .env        # 填入 LLM Key（可选，默认 mock）
uv run pytest tests/ -v     # 测试
uv run uvicorn src.web.app:app --reload  # 启动 Web
```

## 里程碑

- **M0** 脚手架 + LLM provider 多模型抽象
- **M1** 状态层 + 财政系统（内帑/太仓分库、支出分类、宗禄改革、结算）+ 两层记忆
- **M2** base_agent + 编排/史官 + 招募/科举/死亡避免/处置/求见/早朝/任务
- **M3** 事件预兆 + Web UI + 端到端

详见计划文件 `~/.claude/plans/dreamy-drifting-starlight.md`。