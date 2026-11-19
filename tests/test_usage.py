import json
from datetime import datetime, timedelta, timezone

import pytest

from translator import styles, usage
from translator.providers import Usage


def test_cost():
    assert usage.cost_eur({"m": {"in": 3.0, "out": 15.0}}, "m", Usage(1_000_000, 100_000)) == pytest.approx(4.5)


def test_unpriced():
    assert usage.cost_eur({}, "m", Usage(10, 10)) == 0.0


def test_vienna_day_boundary():
    # 23:30 UTC on 2026-11-19 is 00:30 on 2026-11-20 in Vienna (CET, UTC+1)
    assert usage.today(datetime(2026, 11, 19, 23, 30, tzinfo=timezone.utc)) == "2026-11-20"


def test_cap(conn, settings):
    settings.set("prices", json.dumps({"m": {"in": 1.0, "out": 1.0}}))
    settings.set("cap_eur", "1.0")
    t = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
    usage.record(conn, settings, 1, "m", Usage(600_000, 0), now=t)
    assert not usage.cap_reached(conn, settings, now=t)
    usage.record(conn, settings, 1, "m", Usage(500_000, 0), now=t)
    assert usage.cap_reached(conn, settings, now=t)
    assert not usage.cap_reached(conn, settings, now=t + timedelta(days=1))


def test_no_cap(conn, settings):
    usage.record(conn, settings, 1, "m", Usage(1, 1))
    assert not usage.cap_reached(conn, settings)


def test_summary_lists_unpriced(conn, settings):
    styles.seed(conn)
    usage.record(conn, settings, 1, "mystery", Usage(1, 1))
    assert usage.summary(conn, settings)["unpriced_models"] == ["claude-sonnet-5-5", "mystery"]


def test_summary_try_it_row(conn, settings):
    usage.record(conn, settings, None, "m", Usage(1, 1))
    assert usage.summary(conn, settings)["by_style"][0]["label"] == "Try it"


def test_summary_deleted_and_days(conn, settings):
    settings.set("prices", json.dumps({"m": {"in": 1.0, "out": 0.0}}))
    t = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
    usage.record(conn, settings, 99, "m", Usage(1_000_000, 0), now=t)
    usage.record(conn, settings, 99, "m", Usage(1_000_000, 0), now=t - timedelta(days=1))
    s = usage.summary(conn, settings, days=1)
    assert s["by_style"][0]["label"] == "(deleted)"
    assert s["days"] == [{"day": "2026-11-19", "requests": 1, "cost_eur": pytest.approx(1.0)}]
    assert s["unpriced_models"] == []
