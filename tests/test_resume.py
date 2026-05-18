"""Tests do parsing de horário de rate-limit."""

from datetime import datetime, timedelta

from win_runner.resume import parse_when


def test_parse_at_pm():
    dt = parse_when("Your usage limit resets at 3:45pm")
    assert dt is not None
    assert dt.hour == 15
    assert dt.minute == 45


def test_parse_at_am():
    dt = parse_when("try again at 8:00am")
    assert dt is not None
    assert dt.hour == 8


def test_parse_at_24h():
    dt = parse_when("resets at 15:30")
    assert dt is not None
    assert dt.hour == 15
    assert dt.minute == 30


def test_parse_in_hours():
    before = datetime.now()
    dt = parse_when("try again in 2 hours")
    after = datetime.now()
    assert dt is not None
    delta = dt - before
    assert timedelta(hours=1, minutes=59) <= delta <= timedelta(hours=2, minutes=1)


def test_parse_in_minutes():
    before = datetime.now()
    dt = parse_when("available in 45 minutes")
    assert dt is not None
    delta = dt - before
    assert timedelta(minutes=44) <= delta <= timedelta(minutes=46)


def test_parse_no_match():
    assert parse_when("some unrelated text") is None
    assert parse_when("") is None


def test_parse_midnight_am():
    dt = parse_when("resets at 12:00am")
    assert dt is not None
    assert dt.hour == 0
