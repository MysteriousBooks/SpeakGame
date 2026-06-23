"""回合协调器（GameEngine）：串起整套循环。

每回合流程（见计划第3节"回合制"）：
  下诏 → 编排解析（分派/处置/财政/任务）→ 相关 agent 执行（信息隔离）→
  史官推演 delta + 财政结算 + 求见汇总 → 代码校验落库 →
  代码判定活跃事件是否解决 → 时间推进触发新历史事件 → 下一回合。

落库顺序：代码财政结算（自然收支）→ 史官 delta（政令效果/临时支出）→ 事件恶化 delta。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.agents.base_agent import load_persona
from src.core.audience import AudienceQueue, AudienceRequest
from src.core.court_session import CourtSession
from src.core.historian import Historian, TurnResult
from src.core.tasks import TaskSystem
from src.core.turn_orchestrator import TurnOrchestrator
from src.core.world_state import WorldState
from src.events.event_engine import EventEngine
from src.finance.economy import FinanceParams, apply_finance_delta, settle
from src.llm.provider import LLMProvider, Message
from src.recruitment.roster import Roster
from src.recruitment.positions import PositionManager



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


@dataclass
class TurnSummary:
    """一回合执行结果（供 Web 展示）。"""

    era: str = ""
    narrative: str = ""
    delta_applied: dict = field(default_factory=dict)
    delta_clipped: dict = field(default_factory=dict)
    finance_settlement: dict = field(default_factory=dict)
    new_events_triggered: list[str] = field(default_factory=list)
    events_resolved: list[str] = field(default_factory=list)
    fail_delta: dict = field(default_factory=dict)
    audience_queue: list[dict] = field(default_factory=list)
    premonitions: list[dict] = field(default_factory=list)
    task: dict | None = None
    execution_public: list[dict] = field(default_factory=dict)  # [{agent_id, name, public}]
    court_speeches: list[dict] = field(default_factory=list)    # 早朝发言 [{speaker_id, speaker_name, public}]


class GameEngine:
    """游戏引擎：持有全部状态，执行回合。"""

    def __init__(
        self,
        config: dict,
        *,
        orchestrator_llm: LLMProvider,
        historian_llm: LLMProvider,
        role_llm: LLMProvider,
    ) -> None:
        self.config = config
        self.state = WorldState.initial(config)
        self.finance = FinanceParams.from_config(config)
        self.roster = Roster(config)
        self.positions = PositionManager()
        self.tasks = TaskSystem()
        self.audience = AudienceQueue()
        self.events = EventEngine(config)
        self.orchestrator = TurnOrchestrator(orchestrator_llm, config=config)
        self.historian = Historian(historian_llm, config=config)
        self.role_llm = role_llm
        self.turn_history: list[dict] = []  # 历史回合摘要（服务端持久，刷新页面可回看）
        self.talent_pool_notification: str | None = None  # 科举流入通知
        self._setup_initial_court()
        self.events.trigger_initial()

    def _setup_initial_court(self) -> None:
        """开局内阁：加载 individual YAML + 激活 recruitment_condition='开局在朝' 的角色。"""
        era = self.state.era_label()
        # 从 individual YAML 加载开局角色
        for fname in ["minister_finance.yaml", "minister_war.yaml", "common_people.yaml"]:
            persona = load_persona(fname)
            self.roster.add_fictional(persona, self.role_llm, era)
        # 从 historical_figures 激活开局在朝角色
        for inst in list(self.roster.instances.values()):
            if inst.persona.recruitment_condition == "开局在朝":
                self.roster.recruit(inst.persona.id, self.role_llm, era)
        # 开局在朝官员占用对应职务
        for inst in self.roster.active_instances():
            if inst.persona.position:
                pos = self.positions.get_by_name(inst.persona.position)
                if pos is not None:
                    try:
                        self.positions.occupy(pos.id, inst.persona.id)
                    except ValueError:
                        pass

    # ---------- 吏部管理 ----------
    def appoint_official(self, persona_id: str, position_id: str) -> dict:
        """从人才库任命官员到指定职务。"""
        era = self.state.era_label()
        inst = self.roster.get(persona_id)
        if inst is None:
            return {"ok": False, "error": f"角色 {persona_id} 不存在"}
        if inst.status not in ("available", "dismissed"):
            return {"ok": False, "error": f"{inst.persona.name} 当前状态不可任命"}
        pos = self.positions.get_by_id(position_id)
        if pos is None:
            return {"ok": False, "error": f"职务 {position_id} 不存在"}
        if pos.occupied_by is not None:
            return {"ok": False, "error": f"职务 {pos.name} 已被占用"}
        if inst.status == "dismissed":
            self.roster.reinstate(persona_id, self.role_llm, era)
        else:
            self.roster.recruit(persona_id, self.role_llm, era)
        self.positions.occupy(position_id, persona_id)
        inst.persona.position = pos.name
        return {"ok": True, "name": inst.persona.name, "position": pos.name}

    def dismiss_official(self, persona_id: str) -> dict:
        """卸任在朝官员。"""
        inst = self.roster.get(persona_id)
        if inst is None:
            return {"ok": False, "error": f"角色 {persona_id} 不存在"}
        if inst.status != "active":
            return {"ok": False, "error": f"{inst.persona.name} 不在朝"}
        self.positions.release_by_persona(persona_id)
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

    # ---------- 状态快照 ----------
    def state_snapshot(self) -> dict:
        """国势面板数据。"""
        return {
            "era": self.state.era_label(),
            "values": dict(self.state.values),
            "finance": {
                "income_monthly": dict(self.finance.income_monthly),
                "expense_monthly": dict(self.finance.expense_monthly),
                "tax_rates": dict(self.finance.tax_rates),
                "zonglu_reform": dict(self.finance.zonglu_reform),
            },
            "active_events": [ae.to_dict() for ae in self.events.active],
            "audience_queue": [r.to_dict() for r in self.audience.items()],
            "active_agents": [
                {
                    "id": a.id,
                    "name": a.name,
                    "position": a.persona.position if hasattr(a, 'persona') else '',
                    "dialogue": inst.dialogue_memory.to_dict() if (inst := self.roster.get(a.id)) else {},
                }
                for a in self.roster.active_agents()
            ],
            "history": list(self.turn_history),
        }

    def situation_text(self) -> str:
        """给编排/史官的局势摘要。"""
        v = self.state.values
        active = self.events.active_unresolved()
        lines = [
            f"时间：{self.state.era_label()}",
            f"国库：{v.get('国库', 0)}，内帑：{v.get('内帑', 0)}，民心：{v.get('民心', 0)}，军力：{v.get('军力', 0)}",
            f"朝堂清洗度：{v.get('朝堂清洗度', 0)}，陕西_民心：{v.get('陕西_民心', 0)}",
            "活跃事件：" + ("；".join(ae.event.name for ae in active) or "无"),
        ]
        return "\n".join(lines)

    def _infer_modifiers(self) -> dict:
        """启发式财政 modifiers（年景/战时/民变）。MVP：默认平年景，按事件/数值推断战时与民变。"""
        wartime = any(
            ae.event.id == "ji_si_zhi_bian" and not ae.resolved for ae in self.events.active
        )
        revolt: list[str] = []
        if self.state.values.get("陕西_民心", 100) < 30:
            revolt.append("陕西")
        return {"harvest": "平", "wartime": wartime, "revolt_provinces": revolt}

    def _active_agents_info(self) -> list[dict]:
        return [
            {
                "id": a.id,
                "name": a.name,
                "skills": list(a.persona.skills),
                "faction": a.persona.faction,
            }
            for a in self.roster.active_agents()
        ]

    # ---------- 求见处理 ----------
    def apply_audience_decisions(self, decisions: dict[str, str]) -> list[dict]:
        """应用玩家对求见队列的处理。decisions: {agent_id: "grant"|"decline"}。

        decline 会扣减该 agent 忠诚（per-agent）。返回处理结果。
        """
        results: list[dict] = []
        for agent_id, action in decisions.items():
            if action == "grant":
                out = self.audience.grant(agent_id)
            else:
                out = self.audience.decline(agent_id)
                # 扣减忠诚
                inst = self.roster.get(agent_id)
                if inst is not None:
                    inst.loyalty = max(0, inst.loyalty + out.loyalty_delta)
            results.append({"agent_id": agent_id, "granted": out.granted, "loyalty_delta": out.loyalty_delta})
        return results

    # ---------- 早朝 ----------
    async def run_court(self, situation: str | None = None) -> tuple[list, list]:
        """执行早朝群聊（在朝 agent 公开议政），返回 (发言, 新增求见)。"""
        court = CourtSession(max_turns=int(self.config.get("game", {}).get("court_turns", 3)))
        speaking = self.roster.active_agents()
        return await court.run(speaking, situation or self.situation_text(), self.audience)

    # ---------- 实时早朝（分轮执行） ----------
    async def start_court_phase(self) -> list[dict]:
        """启动早朝第1轮，返回发言列表。"""
        max_turns = int(self.config.get("game", {}).get("court_turns", 3))
        self._court_session = CourtSession(max_turns=max_turns)
        self._court_session.start()
        speaking = self.roster.active_agents()
        round_speeches = await self._court_session.run_one_round(
            speaking, self.situation_text()
        )
        return [s.to_dict() for s in round_speeches]

    async def interject_court(self, message: str) -> tuple[list[dict], bool]:
        """玩家插话后执行下一轮早朝。返回 (本轮发言, 早朝是否仍活跃)。"""
        if not hasattr(self, "_court_session") or not self._court_session.is_active:
            return [], False
        speaking = self.roster.active_agents()
        round_speeches = await self._court_session.run_one_round(
            speaking, self.situation_text(), player_message=message
        )
        return [s.to_dict() for s in round_speeches], self._court_session.is_active

    def get_court_session_active(self) -> bool:
        """检查当前是否有进行中的早朝。"""
        return hasattr(self, "_court_session") and self._court_session.is_active

    def get_all_court_speeches(self) -> list[dict]:
        """获取早朝全部发言（用于落库）。"""
        if hasattr(self, "_court_session"):
            return [s.to_dict() for s in self._court_session.speeches]
        return []

    def _collect_court_audience_requests(self) -> None:
        """从早朝发言中收集求见请求，加入 audience_queue。"""
        if not hasattr(self, "_court_session"):
            return
        for s in self._court_session.speeches:
            if s.want_audience and s.audience_topic and s.speaker_id != "emperor":
                self.audience.add(AudienceRequest(
                    agent_id=s.speaker_id,
                    agent_name=s.speaker_name,
                    topic=s.audience_topic,
                    urgency="normal",
                ))

    # ---------- 一回合（完整流程，兼容旧接口） ----------
    async def run_turn(self, edict: str, *, audience_decisions: dict | None = None) -> TurnSummary:
        """执行一回合：早朝 → 下诏 → 史官 → 落库。兼容旧接口，一次性跑完。"""
        era = self.state.era_label()
        if audience_decisions:
            self.apply_audience_decisions(audience_decisions)

        # 0. 早朝群聊
        court_speeches_data: list[dict] = []
        try:
            speeches, new_requests = await self.run_court()
            court_speeches_data = [s.to_dict() for s in speeches]
        except Exception:
            pass

        return await self._run_post_court(edict, court_speeches_data, era)

    # ---------- 早朝结束后执行剩余回合 ----------
    async def finish_turn(self, edict: str) -> TurnSummary:
        """早朝结束后执行剩余流程：诏书执行 → 史官 → 落库。"""
        era = self.state.era_label()
        court_speeches_data = self.get_all_court_speeches()
        self._collect_court_audience_requests()
        return await self._run_post_court(edict, court_speeches_data, era)

    async def _run_post_court(self, edict: str, court_speeches_data: list[dict], era: str) -> TurnSummary:
        """早朝后的公共流程：诏书执行 → 史官推演 → 落库 → 时间推进。"""

        # 1. 编排解析诏书
        plan = await self.orchestrator.parse_edict(
            edict,
            turn=self.state.current_month_index(),
            available_agents=self._active_agents_info(),
            situation=self.situation_text(),
            era=era,
        )

        # 2. 处置/财政/任务
        execution_public: list[dict] = []
        if plan.is_execute_death and plan.target:
            self.roster.kill(plan.target)
        elif plan.is_dismiss and plan.target:
            try:
                self.roster.dismiss(plan.target)
            except ValueError:
                pass
        if plan.is_finance_transfer and plan.finance_action:
            self._apply_finance_transfer(plan.finance_action)
        if plan.task:
            t = self.tasks.create(
                plan.task.get("target_agent", ""),
                plan.task.get("content", ""),
                affects=plan.task.get("affects", []),
                success_condition=plan.task.get("success_condition", ""),
                turn=self.state.current_month_index(),
            )
            plan_task_snapshot = t.to_dict()
        else:
            plan_task_snapshot = None

        # 3. 相关 agent 执行（信息隔离，产出公开层）
        for agent_id in plan.dispatch_targets:
            agent = next((a for a in self.roster.active_agents() if a.id == agent_id), None)
            if agent is None:
                continue
            out = await agent.respond(
                f"皇帝下诏：{edict}\n请依诏执行并奏报。",
                "请执行诏书并产出公开层奏报。",
            )
            execution_public.append({"agent_id": agent_id, "name": agent.name, "public": out.public})

        public_outputs = "\n".join(f"{e['name']}：{e['public']}" for e in execution_public) or "（无 agent 执行）"
        edict_and_dispatch = f"诏书：{edict}\n编排：{plan.action}，分派：{plan.dispatch_targets}"

        # 4. 史官推演
        current_month = self.state.current_month_index()
        prems = self.events.upcoming_premonitions(current_month)
        upcoming_text = "; ".join(f"{p['name']}({p['level']})" for p in prems) or "无"
        turn_result: TurnResult = await self.historian.deduce(
            public_outputs=public_outputs,
            world_snapshot=dict(self.state.values),
            finance_params=self.finance,
            edict_and_dispatch=edict_and_dispatch,
            upcoming_events=upcoming_text,
            era=era,
        )

        # 5. 落库：代码财政结算（自然收支）→ 史官 delta → 事件恶化
        modifiers = self._infer_modifiers()
        settlement = settle(self.state.values, self.finance, **modifiers)
        combined_delta = dict(turn_result.delta)
        # 财政自然收支并入国库
        if settlement.treasury_delta:
            combined_delta["国库"] = combined_delta.get("国库", 0) + settlement.treasury_delta
        if settlement.inner_purse_delta:
            combined_delta["内帑"] = combined_delta.get("内帑", 0) + settlement.inner_purse_delta
        if settlement.zonglu_dissatisfaction_delta:
            combined_delta["宗室不满"] = (
                combined_delta.get("宗室不满", 0) + settlement.zonglu_dissatisfaction_delta
            )

        delta_result = self.state.apply_delta(combined_delta)

        # 更新财政参数（史官推演的 finance_delta，下回合结算用新参数）
        if turn_result.finance_delta:
            self.finance = apply_finance_delta(self.finance, turn_result.finance_delta)

        # 事件解决判定 + 恶化
        resolved = self.events.check_resolve(self.state.values)
        fail_delta = self.events.apply_fail_consequences(self.state.values, current_month)
        if fail_delta:
            fail_result = self.state.apply_delta(fail_delta)
            delta_result.applied.update(fail_result.applied)

        # 6. 求见汇总（史官产出的，下回合呈现）
        self.audience.add_from_historian(turn_result.audience_queue, roster=self.roster)

        # 7. 记录事实记忆（factual_notes 写入相关 agent）
        for agent_id in plan.dispatch_targets:
            inst = self.roster.get(agent_id)
            if inst is not None:
                for note in turn_result.factual_notes:
                    inst.factual.add(note, tags=[inst.persona.id, "回合事件"], turn=current_month)

        # 8. 时间推进 + 触发新历史事件
        turn_length = self.config.get("game", {}).get("turn_length", "month")
        crossed = self.state.advance_time(turn_length)
        newly_triggered = self.events.trigger_by_months(crossed)

        summary = TurnSummary(
            era=self.state.era_label(),
            narrative=turn_result.narrative,
            delta_applied=dict(delta_result.applied),
            delta_clipped=dict(delta_result.clipped),
            finance_settlement={
                "income": settlement.income_actual,
                "expense": settlement.expense_actual,
                "net": settlement.net,
            },
            new_events_triggered=[e.name for e in newly_triggered],
            events_resolved=[ae.event.name for ae in resolved],
            fail_delta=fail_delta,
            audience_queue=[r.to_dict() for r in self.audience.items()],
            premonitions=prems,
            task=plan_task_snapshot,
            execution_public=execution_public,
            court_speeches=court_speeches_data,
        )
        # 服务端持久化回合摘要（刷新页面可回看，最多保留 30 回合）
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
            }
        )
        self.turn_history = self.turn_history[-30:]

        # 9. 压缩对话历史
        await self.compress_dialogues()

        return summary

    def _apply_finance_transfer(self, finance_action: dict) -> None:
        """执行财政划拨（内帑→国库允许；国库→内帑默认拒绝/force 触发哗然）。"""
        from src.finance.economy import transfer_inner_to_treasury, transfer_treasury_to_inner

        ftype = finance_action.get("type")
        amount = float(finance_action.get("amount", 0))
        if ftype == "inner_to_treasury":
            transfer_inner_to_treasury(self.state.values, amount)
        elif ftype == "treasury_to_inner":
            # 默认拒绝（不 force）；玩家强行则由编排标记，MVP 不自动 force
            transfer_treasury_to_inner(self.state.values, amount, force=False)

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
                pass
        return compressed

    # ---------- 存档 ----------
    def save(self, path: str | Path) -> None:
        import json

        data = {
            "state": self.state.to_dict(),
            "finance": {
                "income_monthly": self.finance.income_monthly,
                "expense_monthly": self.finance.expense_monthly,
                "tax_rates": self.finance.tax_rates,
                "zonglu_reform": self.finance.zonglu_reform,
            },
            "roster": self.roster.to_dict(),
            "positions": self.positions.to_dict(),
            "tasks": self.tasks.to_dict(),
            "audience": self.audience.to_dict(),
            "events": self.events.to_dict(),
        }
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(
        cls,
        path: str | Path,
        config: dict,
        *,
        orchestrator_llm: LLMProvider,
        historian_llm: LLMProvider,
        role_llm: LLMProvider,
    ) -> "GameEngine":
        import json

        data = json.loads(Path(path).read_text(encoding="utf-8"))
        eng = cls(
            config,
            orchestrator_llm=orchestrator_llm,
            historian_llm=historian_llm,
            role_llm=role_llm,
        )
        eng.state = WorldState.from_dict(data["state"], eng.state.bounds)
        fin = data["finance"]
        eng.finance = FinanceParams(
            income_monthly=fin["income_monthly"],
            expense_monthly=fin["expense_monthly"],
            tax_rates=fin["tax_rates"],
            zonglu_reform=fin["zonglu_reform"],
        )
        eng.tasks = TaskSystem.from_dict(data["tasks"])
        eng.audience = AudienceQueue.from_dict(data["audience"])
        eng.events = EventEngine.from_dict(data["events"], config)
        # 恢复职务状态（旧存档兼容）
        if "positions" in data:
            eng.positions = PositionManager.from_dict(data["positions"])
        # roster 的 agent 对象需重建（llm 注入）
        era = eng.state.era_label()
        for inst_id, inst_data in data["roster"].get("instances", {}).items():
            inst = eng.roster.get(inst_id)
            if inst is not None and inst.status == "active":
                inst.agent = eng.roster.make_agent(inst_id, role_llm, era)
        return eng

    # ---------- 新游戏 ----------
    def new_game(self) -> None:
        """重置引擎到初始状态（新游戏）。"""
        cfg = self.config
        self.state = WorldState.initial(cfg)
        self.finance = FinanceParams.from_config(cfg)
        self.roster = Roster(cfg)
        self.positions = PositionManager()
        self.tasks = TaskSystem()
        self.audience = AudienceQueue()
        self.events = EventEngine(cfg)
        self.turn_history.clear()
        self._pending_edict = ""
        self._exam_gongshi = None
        self._exam_rankings = {}
        self._exam_year = 0
        self._setup_initial_court()
        self.events.trigger_initial()

    # ---------- 存档槽位 ----------
    SAVE_DIR = Path("saves")

    def _slot_path(self, slot: int) -> Path:
        return self.SAVE_DIR / f"slot_{slot}"

    def save_to_slot(self, slot: int) -> str:
        """保存到指定槽位。"""
        import json
        slot_dir = self._slot_path(slot)
        slot_dir.mkdir(parents=True, exist_ok=True)
        path = slot_dir / "state.json"
        self.save(str(path))
        hist_path = slot_dir / "history.json"
        hist_path.write_text(
            json.dumps(self.turn_history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(slot_dir)

    def load_from_slot(self, slot: int) -> None:
        """从指定槽位加载。"""
        import json
        slot_dir = self._slot_path(slot)
        path = slot_dir / "state.json"
        if not path.exists():
            raise FileNotFoundError(f"槽位 {slot} 无存档")
        # 用当前 engine 的 llm 配置重建
        data = json.loads(path.read_text(encoding="utf-8"))
        self.state = WorldState.from_dict(data["state"], self.state.bounds)
        fin = data["finance"]
        self.finance = FinanceParams(
            income_monthly=fin["income_monthly"],
            expense_monthly=fin["expense_monthly"],
            tax_rates=fin["tax_rates"],
            zonglu_reform=fin["zonglu_reform"],
        )
        self.tasks = TaskSystem.from_dict(data["tasks"])
        self.audience = AudienceQueue.from_dict(data["audience"])
        self.events = EventEngine.from_dict(data["events"], self.config)
        # roster 重建
        self.roster = Roster(self.config)
        era = self.state.era_label()
        for inst_id, inst_data in data["roster"].get("instances", {}).items():
            saved_inst = inst_data
            persona = next(
                (p for p in self.roster.instances.values() if p.persona.id == inst_id),
                None,
            )
            if persona is None:
                continue
            persona.status = saved_inst.get("status", "available")
            persona.loyalty = saved_inst.get("loyalty", 70)
            persona.dissatisfaction = saved_inst.get("dissatisfaction", 0)
            persona.safety = saved_inst.get("safety", 50)
            from src.agents.dialogue_memory import DialogueMemory
            persona.dialogue_memory = DialogueMemory.from_dict(saved_inst.get("dialogue_memory", {}))
            if persona.status == "active":
                persona.agent = self.roster.make_agent(inst_id, self.role_llm, era)
        # 恢复职务状态（旧存档兼容）
        if "positions" in data:
            self.positions = PositionManager.from_dict(data["positions"])
        # 恢复 turn_history
        hist_path = slot_dir / "history.json"
        if hist_path.exists():
            self.turn_history = json.loads(hist_path.read_text(encoding="utf-8"))

    @staticmethod
    def list_saves() -> list[dict]:
        """列出所有存档槽位信息。"""
        import json
        slots = []
        for i in range(1, 4):
            slot_dir = GameEngine.SAVE_DIR / f"slot_{i}"
            state_path = slot_dir / "state.json"
            if state_path.exists():
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
