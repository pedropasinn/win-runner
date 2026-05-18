"""Tests da tradução cron → schtasks args."""

import pytest

from win_runner.scheduler import translate_cron


def test_daily():
    t = translate_cron("0 9 * * *")
    assert t.args == ["/sc", "daily", "/st", "09:00"]
    assert "diariamente" in t.human


def test_weekly():
    t = translate_cron("30 14 * * 1")
    assert t.args == ["/sc", "weekly", "/d", "MON", "/st", "14:30"]


def test_weekly_sunday_zero_and_seven():
    t0 = translate_cron("0 6 * * 0")
    t7 = translate_cron("0 6 * * 7")
    assert t0.args == t7.args
    assert "/d" in t0.args and "SUN" in t0.args


def test_monthly():
    t = translate_cron("0 3 15 * *")
    assert t.args == ["/sc", "monthly", "/d", "15", "/st", "03:00"]


def test_minute_interval():
    t = translate_cron("*/15 * * * *")
    assert t.args == ["/sc", "minute", "/mo", "15"]


def test_hourly_interval():
    t = translate_cron("0 */2 * * *")
    assert t.args == ["/sc", "hourly", "/mo", "2"]


def test_invalid_field_count():
    with pytest.raises(ValueError, match="5 campos"):
        translate_cron("0 9 *")


def test_unsupported_combination():
    # combinar dom != * e dow != * é raro em cron e schtasks não tem mapping direto
    with pytest.raises(ValueError):
        translate_cron("0 9 15 * 1")


def test_unsupported_month_field():
    with pytest.raises(ValueError):
        translate_cron("0 9 * 6 *")
