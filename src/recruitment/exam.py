"""科举系统：乡试 → 会试 → 殿试 + 进士人格生成（新增 agent）。

设计要点（见计划第3节"科举系统"）：
- 三年一科（可配置每年）；科举作为周期性历史事件，触发前有预兆。
- 乡试（秋闱）→ 举人；会试（春闱）→ 贡士；殿试 → 玩家定名次授官。
- 殿试由玩家决定名次；难度等级控制信息可见性（easy 显示能力倾向，normal 答卷+籍贯，hard 仅答卷）。
- 授官后基于籍贯/答卷风格生成人格卡，成为新 agent（active 在朝）。
- 科举 agent 为虚构但符合时代的新人物（无史实死因/正反派元数据，自然死亡按平均寿命）。
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from src.agents.base_agent import PersonaCard
from src.llm.provider import LLMProvider
from src.recruitment.roster import Roster

# 虚构举人姓氏/名字池（符合明代命名风格）
_SURNAMES = list("王李张刘陈杨赵黄周吴徐孙朱马胡郭林何高梁")
_GIVEN_NAMES_M = ["维崇", "承业", "廷表", "克让", "彦和", "士弘", "孟坚", "叔达", "子厚", "公辅"]
_ABILITIES = ["经世", "文章", "兵略", "理刑", "钱谷", "水利", "辞章", "历算"]
_PROVINCES = ["顺天", "应天", "山东", "山西", "河南", "陕西", "浙江", "江西", "湖广", "福建", "四川"]
_BACKGROUNDS = ["寒门苦读", "耕读世家", "落第再试", "边地寒微", "官学廪生", "乡绅子弟"]

_WEAKNESSES = ["马虎", "贪墨", "刚愎", "怯懦", "刻板", "圆滑", "急躁", "懒散", "好色", "嗜酒"]

# 可授官职（按名次分组）
# 前三甲固定职位
POSITIONS_TOP3 = {
    1: [{"id": "xiuzhuan", "name": "翰林院修撰", "rank_min": 1, "rank_max": 1, "desc": "正六品，掌修国史"}],
    2: [{"id": "bianxiu", "name": "翰林院编修", "rank_min": 2, "rank_max": 3, "desc": "正七品，掌修国史"}],
    3: [{"id": "bianxiu", "name": "翰林院编修", "rank_min": 2, "rank_max": 3, "desc": "正七品，掌修国史"}],
}
# 二甲及以后可选职位
POSITIONS_ERJIA = [
    {"id": "shujishi", "name": "翰林院庶吉士", "desc": "储才学习，三年后授官", "skill_bonus": ["文章", "辞章"]},
    {"id": "jishizhong", "name": "六科给事中", "desc": "监察六部，可封驳诏书", "skill_bonus": ["经世", "理刑"]},
    {"id": "yushi", "name": "监察御史", "desc": "巡按地方，纠劾百官", "skill_bonus": ["理刑", "经世"]},
    {"id": "zhushi", "name": "六部主事", "desc": "各部实务，掌文书案牍", "skill_bonus": ["钱谷", "水利"]},
    {"id": "zhixian", "name": "知县", "desc": "外放一县，掌民政赋税", "skill_bonus": ["经世", "钱谷"]},
    {"id": "tuiguan", "name": "推官", "desc": "府级司法，掌刑名狱讼", "skill_bonus": ["理刑"]},
]

def get_positions_for_rank(rank: int) -> list[dict]:
    """根据殿试名次返回可授官职列表。"""
    if rank in POSITIONS_TOP3:
        return POSITIONS_TOP3[rank]
    return POSITIONS_ERJIA

# 答卷风格与性格倾向映射
_ANSWER_STYLE_TO_PERSONALITY = {
    "刚直": "刚直敢谏，不避权贵",
    "温雅": "温雅持重，长于辞令",
    "务实": "务实精干，重钱谷实务",
    "宏阔": "宏阔好谈，善议论时政",
    "谨厚": "谨厚守成，不喜更张",
}


def _gen_name(used: set[str]) -> str:
    """生成不重复的虚构姓名。"""
    for _ in range(200):
        name = random.choice(_SURNAMES) + random.choice(_GIVEN_NAMES_M)
        if name not in used:
            used.add(name)
            return name
    # 兜底加序号
    name = f"{random.choice(_SURNAMES)}某{len(used)}"
    used.add(name)
    return name


@dataclass
class Candidate:
    """科举考生（举人/贡士）。"""

    id: str
    name: str
    origin_province: str
    answer_text: str
    ability_tendency: str
    background: str
    answer_style: str  # 答卷风格，用于人格生成

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "origin_province": self.origin_province,
            "answer_text": self.answer_text,
            "ability_tendency": self.ability_tendency,
            "background": self.background,
            "answer_style": self.answer_style,
        }


def generate_candidates(n: int, *, used_names: set[str] | None = None, seed=None) -> list[Candidate]:
    """系统生成 n 个虚构考生（举人/贡士）。seed 用于测试可复现。"""
    rng = random.Random(seed) if seed is not None else random
    used = used_names if used_names is not None else set()
    candidates: list[Candidate] = []
    for i in range(n):
        name = _gen_name(used)
        style = rng.choice(list(_ANSWER_STYLE_TO_PERSONALITY.keys()))
        candidates.append(
            Candidate(
                id=f"candidate_{i}_{abs(hash(name)) % 100000}",
                name=name,
                origin_province=rng.choice(_PROVINCES),
                answer_text=f"臣对：{style}之论，{rng.choice(['论政', '论兵', '论财', '论边'])}…",
                ability_tendency=rng.choice(_ABILITIES),
                background=rng.choice(_BACKGROUNDS),
                answer_style=style,
            )
        )
    return candidates


def exam_display(candidate: Candidate, difficulty: str) -> dict:
    """按难度返回殿试可见信息。easy 显示能力倾向；normal 答卷+籍贯；hard 仅答卷。"""
    info: dict = {"id": candidate.id, "name": candidate.name}
    if difficulty == "easy":
        info["ability_tendency"] = candidate.ability_tendency
        info["origin_province"] = candidate.origin_province
        info["answer_text"] = candidate.answer_text
        info["background"] = candidate.background
    elif difficulty == "normal":
        info["origin_province"] = candidate.origin_province
        info["answer_text"] = candidate.answer_text
    else:  # hard
        info["answer_text"] = candidate.answer_text
    return info


def generate_jinshi_persona(
    candidate: Candidate,
    rank: int,
    config: dict,
    chongzhen_year: int,
    position: dict | None = None,
) -> PersonaCard:
    """授官：基于籍贯/答卷风格生成进士人格卡，成为新 agent。

    chongzhen_year 为崇祯纪年（如 3 = 崇祯三年），内部转真实公元年计算出生/死亡年。
    虚构角色无史实死因/正反派元数据；自然死亡按平均寿命（士绅官员略高）。
    """
    avg = int(config.get("game", {}).get("average_lifespan", 50))
    real_year = 1627 + chongzhen_year
    age = 25 + (rank % 10)  # 25~34 岁中进士
    born_year = real_year - age
    historical_death_year = born_year + avg + 3  # 士绅官员微调 +3
    rank_label = {1: "状元", 2: "榜眼", 3: "探花"}.get(rank, f"二甲第{rank - 3}")
    personality = _ANSWER_STYLE_TO_PERSONALITY.get(candidate.answer_style, "持重")
    skills = [candidate.ability_tendency]
    if candidate.ability_tendency in ("经世", "钱谷"):
        skills.append("理财")
    if candidate.ability_tendency == "兵略":
        skills.append("军事")
    pos_name = position["name"] if position else rank_label
    gender = random.choice(["男", "女"])
    weaknesses = random.sample(_WEAKNESSES, k=random.randint(1, 2))
    return PersonaCard(
        id=f"jinshi_{candidate.id}",
        name=candidate.name,
        courtesy="",
        gender=gender,
        weaknesses=weaknesses,
        faction="新科进士",
        skills=skills,
        personality=personality,
        relations={},
        historical_alignment="",  # 虚构角色无历史评价
        born_year=born_year,
        historical_death_year=historical_death_year,
        death_cause={"type": "natural", "desc": "自然病亡"},
        recruitment_condition=f"崇祯{chongzhen_year}年殿试{rank_label}，授{pos_name}",
    )


class ExamSystem:
    """科举系统：三级流程至殿试授官。"""

    def __init__(self, config: dict) -> None:
        self.config = config
        self._used_names: set[str] = set()

    @property
    def cycle_years(self) -> int:
        return int(self.config.get("game", {}).get("exam_cycle_years", 3))

    def is_exam_year(self, year: int) -> bool:
        """科举年（首科年起每 cycle_years 一科）。首科崇祯三年。"""
        first_exam = 3
        if year < first_exam:
            return False
        return (year - first_exam) % self.cycle_years == 0

    def xiangshi(self, year: int, *, n: int = 20, seed=None) -> list[Candidate]:
        """乡试：各省生员应试，中者为举人。"""
        return generate_candidates(n, used_names=self._used_names, seed=seed)

    def huishi(self, candidates: list[Candidate], *, n_passed: int = 8) -> list[Candidate]:
        """会试：举人赴京应试，筛选取 n_passed 名贡士。"""
        return candidates[:n_passed]

    def dianshi(
        self, gongshi: list[Candidate], ranking: list[str] | None = None
    ) -> list[tuple[Candidate, int]]:
        """殿试：玩家定名次。ranking 为玩家给出的考生 id 顺序（第一名=状元）。

        未提供 ranking 时按贡士顺序默认排定。
        """
        if ranking is None:
            return [(c, i + 1) for i, c in enumerate(gongshi)]
        id_to_cand = {c.id: c for c in gongshi}
        ordered: list[tuple[Candidate, int]] = []
        for rank, cid in enumerate(ranking, start=1):
            if cid in id_to_cand:
                ordered.append((id_to_cand[cid], rank))
        # 未列入的考生追加
        ranked_ids = {cid for cid in ranking}
        for c in gongshi:
            if c.id not in ranked_ids:
                ordered.append((c, len(ordered) + 1))
        return ordered

    def appoint(
        self,
        ranked: list[tuple[Candidate, int]],
        roster: Roster,
        llm: LLMProvider,
        year: int,
        era: str,
    ) -> list:
        """授官：为每位进士生成人格卡加入 roster（active 在朝）。返回新增 agent。"""
        new_agents = []
        for candidate, rank in ranked:
            persona = generate_jinshi_persona(candidate, rank, self.config, year)
            agent = roster.add_fictional(persona, llm, era)
            new_agents.append(agent)
        return new_agents

    def appoint_one(
        self,
        candidate_id: str,
        position_id: str,
        gongshi: list[Candidate],
        rankings: dict[str, int],
        roster: Roster,
        llm: LLMProvider,
        year: int,
        era: str,
    ) -> tuple:
        """单人授官：为一个贡士选择职位并授官。返回 (agent, position_name)。

        candidate_id: 贡士 id
        position_id: 职位 id（前三甲固定，二甲可选）
        rankings: {candidate_id: rank} 名次映射
        """
        candidate = next((c for c in gongshi if c.id == candidate_id), None)
        if candidate is None:
            raise KeyError(f"贡士 {candidate_id} 不存在")
        rank = rankings.get(candidate_id, len(rankings) + 1)
        positions = get_positions_for_rank(rank)
        position = next((p for p in positions if p["id"] == position_id), None)
        if position is None:
            raise ValueError(f"职位 {position_id} 不适用于名次 {rank}")
        persona = generate_jinshi_persona(candidate, rank, self.config, year, position)
        agent = roster.add_fictional(persona, llm, era)
        return agent, position["name"]
