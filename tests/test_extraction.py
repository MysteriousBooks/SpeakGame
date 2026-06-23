"""测试对话诏书提取逻辑。"""

import pytest
from src.core.game_engine import ExtractedSuggestion, ExtractionResult


class TestExtractedSuggestion:
    def test_policy_suggestion(self):
        s = ExtractedSuggestion(
            type="policy", content="减免陕西赋税",
            source_agent_id="hu_bu", source_agent_name="户部尚书",
        )
        assert s.type == "policy"
        assert s.content == "减免陕西赋税"

    def test_appoint_suggestion(self):
        s = ExtractedSuggestion(
            type="appoint", content="举荐李自成为陕西巡抚",
            source_agent_id="bing_bu", source_agent_name="兵部尚书",
            target_person_name="李自成",
            target_position_name="陕西巡抚",
        )
        assert s.type == "appoint"
        assert s.target_person_name == "李自成"

    def test_extraction_result_empty(self):
        r = ExtractionResult()
        assert r.policy_suggestions == []
        assert r.personnel_suggestions == []

    def test_extraction_result_with_items(self):
        r = ExtractionResult(
            policy_suggestions=[
                ExtractedSuggestion(type="policy", content="a", source_agent_id="x", source_agent_name="X"),
            ],
            personnel_suggestions=[
                ExtractedSuggestion(type="appoint", content="b", source_agent_id="y", source_agent_name="Y"),
            ],
        )
        assert len(r.policy_suggestions) == 1
        assert len(r.personnel_suggestions) == 1
