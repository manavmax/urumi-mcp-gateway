"""Timezone handling (ADR-054): system-prompt stamping with a fallback zone.

The frozen-clock cases pin the one moment where IST and UTC disagree about
"today": 2026-10-21 18:30 UTC is already 2026-10-22 00:00 IST, so an order
question asked "today" must resolve to a different date per zone.
"""

from __future__ import annotations

from datetime import datetime as _real_datetime
from zoneinfo import ZoneInfo

import pytest


class FrozenDatetime(_real_datetime):
    """freezegun-style clock: class attributes freeze `now()` for the test."""

    _frozen: _real_datetime = _real_datetime(2026, 10, 21, 18, 30, 0, tzinfo=ZoneInfo("UTC"))

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls._frozen
        return cls._frozen.astimezone(tz)


@pytest.fixture
def frozen_clock(monkeypatch):
    """Freeze datetime.now everywhere in chat.agent's system-prompt builder.

    build_system_prompt does `from datetime import datetime` INSIDE the function,
    so patching the module attribute on the datetime MODULE is what takes effect.
    """
    import datetime as datetime_module

    monkeypatch.setattr(datetime_module, "datetime", FrozenDatetime)
    return FrozenDatetime._frozen


def _settings_with(default_tz: str):
    from config import Settings

    return Settings(default_timezone=default_tz)


def test_prompt_stamps_client_tz_around_midnight_ist(frozen_clock, monkeypatch):
    """18:30 UTC = midnight IST: the IST prompt must say the 22nd, not the 21st."""
    import config
    from chat.agent import build_system_prompt

    monkeypatch.setattr(config, "get_settings", lambda: _settings_with("UTC"))
    prompt = build_system_prompt("Asia/Kolkata")
    assert "Asia/Kolkata" in prompt
    assert "22 October 2026" in prompt
    assert "21 October 2026" not in prompt


def test_prompt_stamps_utc_when_client_is_utc(frozen_clock, monkeypatch):
    """The same frozen instant in UTC is still the 21st."""
    import config
    from chat.agent import build_system_prompt

    monkeypatch.setattr(config, "get_settings", lambda: _settings_with("Asia/Kolkata"))
    prompt = build_system_prompt("UTC")
    assert "UTC" in prompt
    assert "21 October 2026" in prompt
    assert "22 October 2026" not in prompt


def test_prompt_falls_back_to_configured_default(frozen_clock, monkeypatch):
    """No client tz -> the configured gateway.defaultTimezone (Asia/Kolkata local)."""
    import config
    from chat.agent import build_system_prompt

    monkeypatch.setattr(config, "get_settings", lambda: _settings_with("Asia/Kolkata"))
    prompt = build_system_prompt(None)
    assert "Asia/Kolkata" in prompt
    assert "22 October 2026" in prompt


def test_prompt_falls_back_on_invalid_client_tz(frozen_clock, monkeypatch):
    """An invalid client tz must not leak into the prompt; the default applies."""
    import config
    from chat.agent import build_system_prompt

    monkeypatch.setattr(config, "get_settings", lambda: _settings_with("Asia/Kolkata"))
    prompt = build_system_prompt("Mars/Olympus_Mons")
    assert "Mars" not in prompt
    assert "Asia/Kolkata" in prompt


def test_prompt_no_stamp_when_default_also_invalid(monkeypatch):
    """Invalid client tz AND invalid configured default: bare prompt, no context line."""
    import config
    from chat.agent import SYSTEM_PROMPT, build_system_prompt

    monkeypatch.setattr(config, "get_settings", lambda: _settings_with("Not/AZone"))
    prompt = build_system_prompt(None)
    assert prompt == SYSTEM_PROMPT
    assert "local time" not in prompt


def test_client_tz_wins_over_default(frozen_clock, monkeypatch):
    """A valid browser tz takes precedence over the configured default."""
    import config
    from chat.agent import build_system_prompt

    monkeypatch.setattr(config, "get_settings", lambda: _settings_with("Asia/Kolkata"))
    prompt = build_system_prompt("Europe/Berlin")
    assert "Europe/Berlin" in prompt
    assert "Asia/Kolkata" not in prompt


# ---- route-side validation (routes/chat.py::_valid_tz) ----


def test_valid_tz_accepts_iana_name():
    from routes.chat import _valid_tz

    assert _valid_tz("Asia/Kolkata") == "Asia/Kolkata"
    assert _valid_tz("Europe/Berlin") == "Europe/Berlin"


def test_valid_tz_rejects_garbage():
    from routes.chat import _valid_tz

    assert _valid_tz("Mars/Olympus_Mons") is None
    assert _valid_tz("") is None
    assert _valid_tz(None) is None
    assert _valid_tz("x" * 65) is None
    assert _valid_tz("../../etc/passwd") is None
