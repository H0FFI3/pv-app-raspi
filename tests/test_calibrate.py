import pytest

from tools.calibrate import suggest_system_loss


def test_calibration_uses_the_median_of_eligible_hours():
    records = [{
        "hourly": [
            {"actual_kwh": 8, "potential_kwh": 10},
            {"actual_kwh": 9, "potential_kwh": 10},
            {"actual_kwh": 10, "potential_kwh": 10, "curtailed": "battery"},
            {"actual_kwh": 1, "potential_kwh": 0.1},
        ],
    }]

    proposal, count = suggest_system_loss(records, current_loss=0.2)

    assert count == 2
    assert proposal == pytest.approx(0.32)


def test_calibration_returns_no_proposal_without_eligible_hours():
    assert suggest_system_loss([{"hourly": [{"actual_kwh": None, "potential_kwh": 2}]}], 0.14) == (None, 0)
