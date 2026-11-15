from datetime import datetime, timezone

from pvapp.health import health_payload


def test_health_payload_reports_fresh_success_without_internal_details():
    result = health_payload(
        {
            "last_success_date": "2026-10-18",
            "last_success_at": "2026-10-18T05:30:00+00:00",
            "last_ok": True,
            "last_message": "internal path C:\\secret\\key",
        },
        datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc),
        36,
    )

    assert result == {
        "ok": True,
        "last_success_date": "2026-10-18",
        "age_hours": 6.5,
        "last_message": "Die letzte Aktualisierung war erfolgreich.",
    }


def test_health_payload_reports_stale_or_missing_success():
    now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)

    stale = health_payload({"last_success_date": "2026-10-18"}, now, 36)
    missing = health_payload({"last_message": "secret"}, now, 36)

    assert stale["ok"] is False and stale["age_hours"] == 60
    assert stale["last_message"] == "Die letzte erfolgreiche Aktualisierung ist veraltet."
    assert missing == {
        "ok": False,
        "last_success_date": None,
        "age_hours": None,
        "last_message": "Noch keine erfolgreiche Aktualisierung.",
    }
