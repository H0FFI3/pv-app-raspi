"""Vollständigkeitsstatus der lokalen Tageshistorie (ohne Ein-/Ausgabe)."""

from __future__ import annotations

from datetime import date, timedelta


def build_completeness(
    records: list[dict],
    data_start: date,
    today: date,
    backfill_max_days: int,
) -> list[dict]:
    """Liefert einen Status je Tag von ``data_start`` bis gestern."""
    yesterday = today - timedelta(days=1)
    if yesterday < data_start:
        return []
    by_day = {
        record["date"]: record
        for record in records
        if isinstance(record, dict) and isinstance(record.get("date"), str)
    }
    backfill_start = yesterday - timedelta(days=max(1, backfill_max_days) - 1)
    result = []
    for offset in range((yesterday - data_start).days + 1):
        day = data_start + timedelta(days=offset)
        record = by_day.get(day.isoformat())
        if record is None:
            result.append({
                "date": day.isoformat(),
                "status": "übersprungen" if day < backfill_start else "fehlt",
                "reason": "außerhalb des Backfill-Fensters" if day < backfill_start else None,
                "flags": [],
            })
            continue
        flags = []
        if record.get("weather_source") == "forecast":
            flags.append("Wetter=forecast")
        if not record.get("hourly"):
            flags.append("ohne Stundenprofil")
        if not record.get("signals_checked") and not any(
            point.get(key) is not None
            for point in record.get("hourly", [])
            if isinstance(point, dict)
            for key in ("soc_pct", "feed_in_w", "feed_in_max_w", "feed_in_share_at_limit")
        ):
            flags.append("ohne Signale")
        quality = record.get("quality")
        if isinstance(quality, dict):
            quality_flags = quality.get("flags", [])
            if isinstance(quality_flags, list) and quality_flags:
                flags.append("Qualitäts-Flag")
        status = flags[0] if flags else "ok"
        result.append({"date": day.isoformat(), "status": status, "reason": None, "flags": flags})
    return result
