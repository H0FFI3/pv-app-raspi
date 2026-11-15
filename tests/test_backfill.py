import argparse
import asyncio
from datetime import date, timedelta

import pandas as pd

from pvapp import app, sources


START = date(2026, 10, 13)
TODAY = date(2026, 10, 16)


def fake_sources(days, missing_weather_days=()):
    missing_weather_days = set(missing_weather_days)
    weather_days = [day for day in days if day not in missing_weather_days]
    index = pd.DatetimeIndex(
        [
            pd.Timestamp(day.isoformat(), tz="Europe/Berlin") + pd.Timedelta(minutes=30 + hour * 60)
            for day in weather_days
            for hour in range(24)
        ]
    )
    frame = pd.DataFrame(
        {
            "temp_air": 15.0,
            "wind_speed": 1.0,
            "ghi": 100.0,
            "dni": 100.0,
            "dhi": 20.0,
        },
        index=index,
    )
    weather = sources.WeatherData(
        frame=frame,
        elevation=0.0,
        sunshine_hours={day: 3.0 for day in weather_days},
        source_by_day={day: "forecast" for day in weather_days},
    )
    actual = sources.ActualResult(
        inverter_power_kw=6.0,
        energy={day: 5.0 for day in weather_days},
        hourly={day: {} for day in weather_days},
    )
    return weather, actual


def patch_collection(monkeypatch, days, missing_weather_days=()):
    weather, actual = fake_sources(days, missing_weather_days)
    monkeypatch.setattr(
        app.model,
        "estimate_hourly_potential",
        lambda frame, *args: pd.Series(1.0, index=frame.index),
    )
    return weather, actual


async def _resolved(value):
    return value


def test_plan_days_collects_three_missing_days(make_config):
    days = [START + timedelta(days=offset) for offset in range(3)]
    plan = app.plan_days(set(), TODAY, START, 14)

    assert plan.days == days
    assert not plan.skipped_older


def test_stored_yesterday_is_not_requested_again():
    yesterday = TODAY - timedelta(days=1)

    plan = app.plan_days({yesterday}, TODAY, yesterday, 14)

    assert plan.days == []
    assert plan.up_to_date


def test_missing_weather_skips_only_that_day(monkeypatch, make_config):
    days = [START + timedelta(days=offset) for offset in range(3)]
    missing = days[1]
    weather, actual = patch_collection(monkeypatch, days, [missing])

    result = asyncio.run(
        app.collect_records(
            make_config(),
            days,
            load_weather_fn=lambda *args: weather,
            fetch_actuals_fn=lambda *args, **kwargs: _resolved(actual),
        )
    )

    assert [record["date"] for record in result.records] == [days[0].isoformat(), days[2].isoformat()]
    assert result.skipped == {missing: "Wetterdaten sind noch nicht vollständig verfügbar"}


def test_collect_records_preserves_the_weather_source(monkeypatch, make_config):
    weather, actual = patch_collection(monkeypatch, [START])

    result = asyncio.run(
        app.collect_records(
            make_config(),
            [START],
            load_weather_fn=lambda *args: weather,
            fetch_actuals_fn=lambda *args, **kwargs: _resolved(actual),
        )
    )

    assert len(result.records) == 1
    assert result.records[0]["weather_source"] == "forecast"
    assert result.records[0]["actual_kwh"] == 5.0


def test_refresh_recollects_stored_yesterday(monkeypatch, make_config):
    yesterday = TODAY - timedelta(days=1)
    called = []

    async def collect(config, days, **kwargs):
        called.append(days)
        return app.CollectionResult(records=[{
            "date": yesterday.isoformat(),
            "actual_kwh": 5.0,
            "potential_kwh": 6.0,
            "sunshine_hours": 3.0,
            "weather_source": "forecast",
        }])

    monkeypatch.setattr(app.sources, "local_today", lambda timezone: TODAY)
    monkeypatch.setattr(app, "collect_records", collect)
    payload = {"records": [{
        "date": yesterday.isoformat(),
        "actual_kwh": 5.0,
        "potential_kwh": 6.0,
        "sunshine_hours": 3.0,
    }]}

    changed = app.update_history(
        payload,
        make_config(DATA_START_DATE=yesterday),
        argparse.Namespace(refresh=True, refresh_days=0),
    )

    assert changed
    assert called == [[yesterday]]
    assert len(payload["records"]) == 1


def test_backfill_limit_caps_the_range():
    later_today = date(2026, 11, 4)
    yesterday = later_today - timedelta(days=1)

    plan = app.plan_days(set(), later_today, START, 14)

    assert len(plan.days) == 14
    assert plan.days == [yesterday - timedelta(days=offset) for offset in range(13, -1, -1)]
    assert plan.skipped_older == (yesterday - START).days + 1 - 14
