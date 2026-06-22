from src.agents.dialogue_memory import DialogueEntry, DialogueMemory


def test_dialogue_entry_roundtrip():
    e = DialogueEntry(role="player", content="你好", turn=1)
    d = e.to_dict()
    e2 = DialogueEntry.from_dict(d)
    assert e2.role == "player"
    assert e2.content == "你好"
    assert e2.turn == 1


def test_dialogue_memory_add_exchange():
    m = DialogueMemory()
    m.add_exchange("player", "你好", 1)
    m.add_exchange("agent", "臣在", 1)
    assert len(m.exchanges) == 2
    assert m.exchanges[0].role == "player"
    assert m.exchanges[1].role == "agent"


def test_dialogue_memory_clear():
    m = DialogueMemory()
    m.add_exchange("player", "你好", 1)
    m.clear_exchanges()
    assert len(m.exchanges) == 0


def test_dialogue_memory_roundtrip():
    m = DialogueMemory(compressed_summary="摘要")
    m.add_exchange("player", "你好", 1)
    d = m.to_dict()
    m2 = DialogueMemory.from_dict(d)
    assert m2.compressed_summary == "摘要"
    assert len(m2.exchanges) == 1
    assert m2.exchanges[0].content == "你好"


def test_dialogue_memory_empty_roundtrip():
    m = DialogueMemory()
    d = m.to_dict()
    m2 = DialogueMemory.from_dict(d)
    assert m2.compressed_summary == ""
    assert m2.exchanges == []
