from datetime import datetime, timezone

import pytest

from src import cache


class FakeDateTime(datetime):
    """A datetime whose now() is a fixed moment, so we can test the 5 a.m. Eastern rollover."""
    fixed = None

    @classmethod
    def now(cls, tz=None):
        return cls.fixed.astimezone(tz) if tz else cls.fixed


@pytest.mark.parametrize("utc, betting_day", [
    ("2026-10-26 12:00", "2026-10-26"),   # 8 a.m. Eastern Monday
    ("2026-10-27 00:30", "2026-10-26"),   # 8:30 p.m. Eastern Monday: UTC says Tuesday, the betting day says Monday
    ("2026-10-27 08:30", "2026-10-26"),   # 4:30 a.m. Eastern Tuesday: still Monday's slate
    ("2026-10-27 09:30", "2026-10-27"),   # 5:30 a.m. Eastern Tuesday: new day
    ("2026-12-01 10:30", "2026-12-01"),   # winter (EST): 5:30 a.m. Eastern is 10:30 UTC
    ("2026-12-01 09:30", "2026-11-30"),   # 4:30 a.m. EST: still the day before
])
def test_betting_day_rolls_over_at_5am_eastern(monkeypatch, utc, betting_day):
    FakeDateTime.fixed = datetime.strptime(utc, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    monkeypatch.setattr(cache, "datetime", FakeDateTime)
    assert cache.today() == betting_day


def test_evening_lookups_still_hit_the_cache_after_utc_midnight(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "c.db")
    monkeypatch.setattr(cache, "datetime", FakeDateTime)
    FakeDateTime.fixed = datetime(2026, 10, 26, 22, 0, tzinfo=timezone.utc)  # 6 p.m. Eastern
    cache.put("odds_x", {"rows": [1]})
    FakeDateTime.fixed = datetime(2026, 10, 27, 1, 30, tzinfo=timezone.utc)  # 9:30 p.m. Eastern, UTC says tomorrow
    assert cache.get("odds_x") == {"rows": [1]}   # no re-buying the same answer
    FakeDateTime.fixed = datetime(2026, 10, 27, 10, 0, tzinfo=timezone.utc)  # 6 a.m. Eastern: a new day
    assert cache.get("odds_x") is None
