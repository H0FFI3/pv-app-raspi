from datetime import date

from pvapp.completeness import build_completeness


def test_completeness_marks_gaps_and_data_issues():
    result = build_completeness(
        [
            {"date": "2026-10-15", "weather_source": "forecast", "hourly": [], "quality": {"flags": ["low_coverage"]}},
        ],
        date(2026, 10, 13),
        date(2026, 10, 17),
        3,
    )

    assert [item["status"] for item in result] == ["übersprungen", "fehlt", "Wetter=forecast", "fehlt"]
    assert result[0]["reason"] == "außerhalb des Backfill-Fensters"
    assert result[2]["flags"] == [
        "Wetter=forecast",
        "ohne Stundenprofil",
        "ohne Signale",
        "Qualitäts-Flag",
    ]


def test_completeness_does_not_list_days_before_the_first_complete_day():
    assert build_completeness([], date(2026, 10, 13), date(2026, 10, 13), 14) == []
