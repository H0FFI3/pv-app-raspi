from datetime import date, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd

from conftest import BASE_ENV
from pvapp import sources


TIMEZONE = BASE_ENV["TIMEZONE"]


def make_payload(local_day):
    timezone = ZoneInfo(TIMEZONE)
    local_times = pd.date_range(
        pd.Timestamp(local_day.isoformat(), tz=timezone) + pd.Timedelta(hours=1),
        periods=24,
        freq="h",
    )
    unix_times = [int(timestamp.tz_convert("UTC").timestamp()) for timestamp in local_times]
    return {
        "elevation": 12,
        "hourly": {
            "time": unix_times,
            "temperature_2m": [15.0] * 24,
            "wind_speed_10m": [1.0] * 24,
            "shortwave_radiation": [100.0] * 24,
            "direct_normal_irradiance": [120.0] * 24,
            "diffuse_radiation": [20.0] * 24,
            "sunshine_duration": [300.0] * 24,
        },
    }


def response(payload, status=200):
    return SimpleNamespace(status_code=status, json=lambda: payload)


def test_yesterday_uses_forecast_and_marks_source(make_config):
    yesterday = date(2026, 10, 15)
    payload = make_payload(yesterday)
    requests = []
    saved = []

    def fake_get(url, params, timeout):
        requests.append((url, params, timeout))
        if url == sources.ARCHIVE_URL:
            return response({"reason": "not yet available"}, 400)
        return response(payload)

    result = sources.load_weather(
        make_config(), yesterday, yesterday, http_get=fake_get, today=yesterday + timedelta(days=1),
        sleep=lambda _: None, raw_data_callback=lambda *item: saved.append(item),
    )

    assert [request[0] for request in requests] == [sources.ARCHIVE_URL, sources.FORECAST_URL]
    assert requests[1][1]["past_days"] == 2
    assert requests[1][1]["timezone"] == "UTC"
    assert result.elevation == 12
    assert result.sunshine_hours[yesterday] == 2.0
    assert result.source_by_day[yesterday] == "forecast"
    assert result.frame.index[0] == pd.Timestamp(f"{yesterday} 00:30", tz=TIMEZONE)
    assert len(saved) == 1 and saved[0][0:2] == ("weather_hourly", None)
    assert saved[0][2]["source"] == "forecast" and saved[0][2]["payload"] == payload


def test_older_days_use_historical_weather_archive(make_config):
    old_day = date(2026, 9, 1)
    payload = make_payload(old_day)
    requests = []

    def fake_get(url, params, timeout):
        requests.append((url, params))
        return response(payload)

    result = sources.load_weather(
        make_config(), old_day, old_day, http_get=fake_get, today=date(2026, 10, 1), sleep=lambda _: None
    )

    assert len(requests) == 1
    assert requests[0][0] == sources.ARCHIVE_URL
    assert requests[0][1]["start_date"] == (old_day - timedelta(days=1)).isoformat()
    assert result.source_by_day[old_day] == "archive"
