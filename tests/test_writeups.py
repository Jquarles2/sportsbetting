from types import SimpleNamespace

import pytest

from src import cache, writeups

PICK = {"PLAYER": "Jayson Tatum", "GAME": "NYK @ BOS", "SIDE": "Over", "LINE": 27.5}
VALUES = [30, 31, 28, 35, 29, 20, 33, 30, 28, 40, 22]


class FakeClient:
    def __init__(self, text="Tatum cleared it.", stop_reason="end_turn"):
        self.calls = []
        self.text, self.stop_reason = text, stop_reason
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        block = SimpleNamespace(type="text", text=self.text)
        return SimpleNamespace(content=[block], stop_reason=self.stop_reason)


@pytest.fixture(autouse=True)
def temp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "c.db")


def test_prompt_contains_the_facts_and_nothing_extra():
    prompt = writeups.build_prompt(PICK, "points", VALUES)
    assert "Jayson Tatum - Over 27.5 points (NYK @ BOS)" in prompt
    assert "[30, 31, 28, 35, 29, 20, 33, 30, 28, 40]" in prompt  # only the last 10
    assert "last 5: 100.0%, last 10: 90.0%, last 20: 81.8%" in prompt


def test_writeup_uses_haiku_and_is_cached():
    client = FakeClient()
    assert writeups.get_writeup(PICK, "points", VALUES, client=client) == "Tatum cleared it."
    call = client.calls[0]
    assert call["model"] == "claude-haiku-5-5" and call["output_config"] == {"effort": "low"}
    assert writeups.get_writeup(PICK, "points", VALUES, client=client) == "Tatum cleared it."
    assert len(client.calls) == 1  # second request came from the cache


def test_empty_response_raises_and_is_not_cached():
    client = FakeClient(text="", stop_reason="refusal")
    with pytest.raises(RuntimeError, match="refusal"):
        writeups.get_writeup(PICK, "points", VALUES, client=client)
    good = FakeClient()
    assert writeups.get_writeup(PICK, "points", VALUES, client=good) == "Tatum cleared it."


def test_missing_key_gives_a_readable_error(monkeypatch):
    monkeypatch.setattr(writeups, "get_secret", lambda name: None)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        writeups.get_writeup(PICK, "points", VALUES)
