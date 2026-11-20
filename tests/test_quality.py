import pytest

from pvapp.quality import build_quality, valid_quality


def test_quality_metrics_and_flags():
    quality = build_quality(
        n_samples=120,
        coverage=0.7,
        integral_kwh=8.0,
        epv=10.0,
        hourly=[{"actual_kwh": 10.0}],
    )

    assert quality["integral_ratio"] == pytest.approx(0.8)
    assert quality["flags"] == ["low_coverage", "epv_mismatch"]


def test_quality_flags_missing_hourly_values():
    quality = build_quality(
        n_samples=0,
        coverage=0.0,
        integral_kwh=0.0,
        epv=0.0,
        hourly=[{"actual_kwh": None}],
    )

    assert "hourly_missing" in quality["flags"]
    assert quality["integral_ratio"] is None


def test_invalid_or_legacy_quality_is_ignored():
    assert valid_quality({"coverage": float("nan")}) is None
    assert valid_quality({"n_samples": 1, "coverage": 0.5, "integral_kwh": 2, "integral_ratio": 1, "flags": []})["flags"] == []
