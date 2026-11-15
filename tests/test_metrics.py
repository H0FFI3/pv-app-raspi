import pytest

from pvapp.metrics import calculate_metrics, performance_ratio, specific_yield


def test_metrics_for_known_example():
    result = calculate_metrics([10, 20], [12, 18])

    assert result["count"] == 2
    assert result["mbe"] == 0
    assert result["rmse"] == pytest.approx(2)
    assert result["rmbd_pct"] == 0
    assert result["mape_pct"] == pytest.approx(15)


def test_metrics_skip_missing_non_finite_and_zero_actual_for_mape():
    result = calculate_metrics([0, None, 10, float("nan")], [2, 4, 12, 3])

    assert result["count"] == 2
    assert result["mbe"] == 2
    assert result["rmbd_pct"] == pytest.approx(40)
    assert result["mape_pct"] == pytest.approx(20)


def test_metrics_return_empty_values_without_valid_pairs():
    assert calculate_metrics([None, float("inf")], [1, 2]) == {
        "count": 0,
        "mbe": None,
        "rmse": None,
        "rmbd_pct": None,
        "mape_pct": None,
    }


def test_specific_yield_and_performance_ratio_known_example():
    assert specific_yield(120, 10) == 12
    assert performance_ratio(120, 10, 15) == pytest.approx(0.8)
    assert performance_ratio(120, 0, 15) is None
