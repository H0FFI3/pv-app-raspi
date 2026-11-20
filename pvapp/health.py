"""Sichere, minimale Statusantwort für den öffentlichen Lese-Endpunkt."""

from __future__ import annotations

from datetime import datetime, time


def health_payload(status: dict, now: datetime, stale_after_hours: int) -> dict:
    """Erzeugt nur Statusfelder, die keine Pfade oder Zugangsdaten enthalten."""
    last_success_date = status.get("last_success_date")
    success_at = None
    try:
        if status.get("last_success_at"):
            success_at = datetime.fromisoformat(status["last_success_at"])
        elif last_success_date:
            success_at = datetime.combine(
                datetime.fromisoformat(last_success_date).date(),
                time.min,
                tzinfo=now.tzinfo,
            )
    except (TypeError, ValueError):
        success_at = None

    age_hours = None
    if success_at is not None:
        if success_at.tzinfo is None and now.tzinfo is not None:
            success_at = success_at.replace(tzinfo=now.tzinfo)
        elif now.tzinfo is None and success_at.tzinfo is not None:
            success_at = success_at.replace(tzinfo=None)
        age_hours = max(0.0, (now - success_at).total_seconds() / 3600)
    ok = age_hours is not None and age_hours <= stale_after_hours
    if age_hours is None:
        message = "Noch keine erfolgreiche Aktualisierung."
    elif status.get("last_ok") is False:
        message = "Der letzte Lauf ist fehlgeschlagen."
    elif not ok:
        message = "Die letzte erfolgreiche Aktualisierung ist veraltet."
    else:
        message = "Die letzte Aktualisierung war erfolgreich."
    return {
        "ok": ok,
        "last_success_date": last_success_date,
        "age_hours": None if age_hours is None else round(age_hours, 1),
        "last_message": message,
    }
