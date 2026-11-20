import json
from datetime import date

from helpers import clear_sky_weather
from pvapp.reference import calculate_tmy_reference, refresh_tmy_reference


def test_tmy_reference_contains_daily_monthly_and_annual_ac_estimates(config):
    weather = clear_sky_weather(
        config.latitude, config.longitude, config.timezone, date(2026, 1, 1), date(2026, 1, 3)
    )

    reference = calculate_tmy_reference(weather, config, 300)

    assert set(reference["daily_kwh_by_month_day"]) == {"01-01", "01-02", "01-03"}
    assert reference["annual_kwh"] > 0
    assert reference["monthly_kwh"]["01"] == reference["annual_kwh"]
    assert len(reference["config_hash"]) == 64


def test_tmy_reference_refresh_uses_an_injected_fetch_and_writes_atomically(config, tmp_path):
    weather = clear_sky_weather(
        config.latitude, config.longitude, config.timezone, date(2026, 1, 1), date(2026, 1, 2)
    )
    path = tmp_path / "tmy_expected.json"
    calls = []

    def fetch(latitude, longitude, timeout):
        calls.append((latitude, longitude, timeout))
        return weather, {"inputs": {"location": {"elevation": 300}}}

    result = refresh_tmy_reference(config, path, fetch=fetch)

    assert calls == [(config.latitude, config.longitude, 30)]
    assert json.loads(path.read_text(encoding="utf-8")) == result
    assert not list(tmp_path.glob("*.tmp"))
