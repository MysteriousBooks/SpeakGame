"""职务管理：CourtPosition 数据类 + PositionManager 管理类。

设计要点：
- 职务是存档的一部分，每个存档可自定义
- 同一职务只能被一位官员占用
- 支持创建自定义职务
"""

from __future__ import annotations

from dataclasses import dataclass, field


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
