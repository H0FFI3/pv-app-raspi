from datetime import date

import pandas as pd
import pytest

from helpers import samples_for_day
from pvapp.sources import aggregate_hourly_pv_power, aggregate_hourly_pv_power_with_quality

TZ = "Europe/Berlin"


def test_constant_power_is_distributed_and_scaled_to_the_daily_value():
    day = date(2026, 10, 14)
    samples = samples_for_day(day, start_hour=8, end_hour=12, watts=1000)  # 4 h * 1 kW = 4 kWh
    hourly = aggregate_hourly_pv_power(samples, day, daily_energy_kwh=5.0, timezone=TZ)
    assert list(hourly) == ["08:00", "09:00", "10:00", "11:00"]
    assert sum(hourly.values()) == pytest_approx(5.0)
    assert all(abs(v - 1.25) < 0.01 for v in hourly.values())


def pytest_approx(value):
    import pytest

    return pytest.approx(value, abs=0.01)


def test_other_days_garbage_and_negative_values_are_ignored():
    day = date(2026, 10, 14)
    samples = samples_for_day(day, 10, 12, 600) + samples_for_day(date(2026, 10, 15), 10, 12, 9999)
    samples += [{"uploadTime": "kaputt", "ppv": 5}, {"uploadTime": "2026-10-14 11:00:00", "ppv": None}]
    hourly = aggregate_hourly_pv_power(samples, day, 1.2, TZ)
    assert set(hourly) == {"10:00", "11:00"}
    assert sum(hourly.values()) == pytest_approx(1.2)


def test_too_few_samples_give_no_profile():
    day = date(2026, 10, 14)
    assert aggregate_hourly_pv_power([], day, 3.0, TZ) == {}
    assert aggregate_hourly_pv_power(samples_for_day(day, 10, 10, 100)[:1], day, 3.0, TZ) == {}


def test_timezone_aware_timestamps_are_converted_to_local_time():
    day = date(2026, 10, 14)
    samples = [
        {"uploadTime": "2026-10-14T08:00:00+00:00", "ppv": 1000},  # 10:00 Ortszeit (MESZ)
        {"uploadTime": "2026-10-14T08:05:00+00:00", "ppv": 1000},
        {"uploadTime": "2026-10-14T08:10:00+00:00", "ppv": 1000},
    ]
    assert list(aggregate_hourly_pv_power(samples, day, 1.0, TZ)) == ["10:00"]


def test_fall_back_day_keeps_unique_hour_labels_and_the_daily_total():
    """25-Stunden-Tag (25.10.2026): früher gingen Proben der doppelten Stunde verloren (ambiguous='NaT')
    und Labels konnten doppelt auftreten. Jetzt: Wanduhr-Zeit, 24 eindeutige Labels, Summe = Tageswert."""
    day = date(2026, 10, 25)
    samples = samples_for_day(day, start_hour=0, end_hour=24, watts=1000)
    samples += [{"uploadTime": f"2026-10-25 02:{m:02d}:30", "ppv": 1000} for m in range(0, 60, 5)]  # zweite 02-Uhr-Stunde
    hourly = aggregate_hourly_pv_power(samples, day, daily_energy_kwh=24.0, timezone=TZ)
    assert len(hourly) == 24 and "02:00" in hourly
    assert sum(hourly.values()) == pytest_approx(24.0)
    # Die zusätzlichen Proben verzerren die Stunde nicht (Zeitintervalle summieren sich weiterhin zu einer Stunde).
    assert hourly["02:00"] == pytest_approx(hourly["03:00"])


def test_all_zero_power_returns_zeros_without_division_error():
    day = date(2026, 10, 14)
    hourly = aggregate_hourly_pv_power(samples_for_day(day, 10, 12, 0), day, 0.0, TZ)
    assert set(hourly.values()) == {0.0}
    assert isinstance(pd.Series(hourly).sum(), float)


def test_quality_metadata_measures_unscaled_integral_and_daylight_coverage():
    day = date(2026, 10, 14)
    samples = samples_for_day(day, start_hour=8, end_hour=12, watts=1000)

    hourly, quality = aggregate_hourly_pv_power_with_quality(
        samples, day, 5.0, TZ, latitude=48.78, longitude=9.18
    )

    assert sum(hourly.values()) == pytest_approx(5.0)
    assert quality["n_samples"] == len(samples)
    assert quality["integral_kwh"] == pytest_approx(4.0)
    assert quality["integral_ratio"] == pytest_approx(0.8)
    assert abs(quality["coverage"] - 4 / 11) < 0.05
    assert {"low_coverage", "epv_mismatch"} <= set(quality["flags"])


# --------------------------------------------------------------------------- Signale (Abregelung)


def test_hourly_signals_take_max_soc_and_mean_absolute_feed_in():
    from pvapp.sources import aggregate_hourly_signals

    day = date(2026, 10, 14)
    samples = [
        {"uploadTime": "2026-10-14 11:00:00", "ppv": 500, "cbat": 95.0, "feedIn": 1000},
        {"uploadTime": "2026-10-14 11:30:00", "ppv": 500, "cbat": 99.5, "feedIn": -3000},
        {"uploadTime": "2026-10-14 12:00:00", "ppv": 500, "cbat": 100, "feedIn": 4000},
        {"uploadTime": "2026-10-15 12:00:00", "ppv": 500, "cbat": 10, "feedIn": 1},  # anderer Tag
    ]
    signals = aggregate_hourly_signals(samples, day, TZ)
    assert signals == {
        "11:00": {"soc_pct": 99.5, "feed_in_w": 2000.0, "feed_in_signed_w": -1000.0, "feed_in_max_w": 1000.0},
        "12:00": {"soc_pct": 100.0, "feed_in_w": 4000.0, "feed_in_signed_w": 4000.0, "feed_in_max_w": 4000.0},
    }


def test_missing_signal_fields_yield_no_keys():
    from pvapp.sources import aggregate_hourly_signals

    day = date(2026, 10, 14)
    samples = samples_for_day(day, 10, 12, 500)  # nur ppv
    assert aggregate_hourly_signals(samples, day, TZ) == {}
    only_soc = [{**s, "cbat": 50} for s in samples]
    result = aggregate_hourly_signals(only_soc, day, TZ)
    assert set(result["10:00"]) == {"soc_pct"}


def test_custom_field_names_are_supported():
    from pvapp.sources import aggregate_hourly_signals

    day = date(2026, 10, 14)
    samples = [{"uploadTime": "2026-10-14 10:00:00", "ppv": 1, "soc": 88, "grid": 700}]
    assert aggregate_hourly_signals(samples, day, TZ, "soc", "grid") == {
        "10:00": {"soc_pct": 88.0, "feed_in_w": 700.0, "feed_in_signed_w": 700.0, "feed_in_max_w": 700.0}
    }


def test_limit_share_captures_a_single_export_peak_but_not_grid_import():
    from pvapp.sources import aggregate_hourly_signals

    day = date(2026, 10, 14)
    samples = [
        {
            "uploadTime": f"2026-10-14 12:{minute:02d}:00",
            "ppv": 1,
            "cbat": 50,
            "feedIn": 4000 if minute == 0 else (-5000 if minute == 5 else 1000),
        }
        for minute in range(0, 60, 5)
    ]

    signals = aggregate_hourly_signals(samples, day, TZ, feed_in_limit_w=4000, feed_in_tolerance=0.95)

    assert signals["12:00"]["feed_in_max_w"] == 4000
    assert signals["12:00"]["feed_in_share_at_limit"] == pytest.approx(1 / 12, abs=0.0001)


def test_signals_survive_the_fall_back_day():
    from pvapp.sources import aggregate_hourly_signals

    day = date(2026, 10, 25)
    samples = [{"uploadTime": f"2026-10-25 {h:02d}:{m:02d}:00", "ppv": 100, "cbat": 40} for h in range(24) for m in (0, 30)]
    assert len(aggregate_hourly_signals(samples, day, TZ)) == 24
