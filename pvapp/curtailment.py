"""Erkennung abgeregelter Stunden (Einspeisebegrenzung, voller Akku).

Reine Funktionen ohne I/O. Eine Stunde gilt als "wahrscheinlich abgeregelt", wenn

1. der Ist-Ertrag deutlich unter dem Potenzial liegt (``min_deficit``) und das Potenzial hoch genug ist, und
2. mindestens ein Hinweis aus den AlphaESS-Leistungsdaten vorliegt:
   - ``limit``:   die mittlere Netzeinspeisung der Stunde liegt am konfigurierten Einspeiselimit, oder
   - ``battery``: der Akku war in der Stunde (nahezu) voll.

Die Erkennung ist eine Heuristik: Sie kann einen Fehler im Modell (z. B. zu optimistisches Potenzial)
nicht von Abregelung trennen. Die Rohsignale werden pro Stunde gespeichert, die Markierung wird bei
jeder Berichtserstellung neu berechnet. Schwellen lassen sich deshalb nachträglich ändern.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, timedelta

REASON_LIMIT = "limit"
REASON_BATTERY = "battery"


@dataclass(frozen=True)
class CurtailmentSettings:
    enabled: bool = True
    soc_full_pct: float = 97.0  # Akku gilt ab diesem Ladestand als voll
    min_deficit: float = 0.20  # Mindestabstand Ist zu Potenzial (Anteil), sonst keine Markierung
    min_potential_kwh: float = 0.3  # darunter ist das Verhältnis Rauschen (Morgen/Abend)
    feed_in_limit_w: float | None = None  # Einspeiselimit in Watt; ohne Angabe wirkt nur "Akku voll"
    feed_in_tolerance: float = 0.95  # Anteil des Limits, ab dem die Einspeisung als "am Limit" gilt


def classify_hour(point: dict, settings: CurtailmentSettings) -> str | None:
    """``"limit"``, ``"battery"`` oder ``None`` für eine Stunde des Tagesprofils."""
    if not settings.enabled:
        return None
    actual, potential = point.get("actual_kwh"), point.get("potential_kwh")
    if actual is None or potential is None or potential < settings.min_potential_kwh:
        return None
    if (potential - actual) / potential < settings.min_deficit:
        return None

    if settings.feed_in_limit_w:
        threshold = settings.feed_in_limit_w * settings.feed_in_tolerance
        share = point.get("feed_in_share_at_limit")
        maximum = point.get("feed_in_max_w")
        if share is not None and share > 0:
            return REASON_LIMIT
        if maximum is not None and maximum >= threshold:
            return REASON_LIMIT
        signed = point.get("feed_in_signed_w")
        if share is None and maximum is None and signed is not None and signed >= threshold:
            return REASON_LIMIT
    soc = point.get("soc_pct")
    if soc is not None and soc >= settings.soc_full_pct:
        return REASON_BATTERY
    return None


def has_signal(point: dict) -> bool:
    return any(
        point.get(key) is not None
        for key in ("soc_pct", "feed_in_w", "feed_in_max_w", "feed_in_share_at_limit", "feed_in_signed_w")
    )


def _baseline(records: list[dict], day: date, settings: CurtailmentSettings) -> float:
    ratios = []
    start = day - timedelta(days=30)
    for record in records:
        try:
            record_day = date.fromisoformat(record["date"])
        except (KeyError, TypeError, ValueError):
            continue
        if not start <= record_day < day:
            continue
        for point in record.get("hourly", []):
            if not has_signal(point):
                continue
            actual, potential = point.get("actual_kwh"), point.get("potential_kwh")
            if actual is None or potential is None or potential < settings.min_potential_kwh:
                continue
            if classify_hour(point, settings) is not None:
                continue
            try:
                ratio = float(actual) / float(potential)
            except (TypeError, ValueError, ZeroDivisionError):
                continue
            if math.isfinite(ratio) and ratio >= 0:
                ratios.append(ratio)
    return statistics.median(ratios) if ratios else 1.0


def annotate_records(records: list[dict], settings: CurtailmentSettings) -> list[dict]:
    """Ergänzt Stunden um ``curtailed`` und Tage um ``curtailment`` = {hours, lost_kwh}.

    ``curtailment`` fehlt, wenn für den Tag keine Akku-/Netzsignale vorliegen (Erkennung nicht möglich).
    ``lost_kwh`` nutzt eine rollende 30-Tage-Baseline; ``lost_kwh_upper`` ist Potenzial minus Ist.
    """
    if not settings.enabled:
        return records
    annotated = []
    for record in records:
        hourly = record.get("hourly")
        if not hourly:
            annotated.append(record)
            continue
        try:
            baseline = _baseline(records, date.fromisoformat(record["date"]), settings)
        except (KeyError, TypeError, ValueError):
            baseline = 1.0
        points, hours, lost, lost_upper, checked = [], 0, 0.0, 0.0, False
        for point in hourly:
            point = dict(point)
            checked = checked or has_signal(point)
            reason = classify_hour(point, settings)
            if reason:
                point["curtailed"] = reason
                hours += 1
                lost_upper += max(0.0, point["potential_kwh"] - point["actual_kwh"])
                lost += max(0.0, point["potential_kwh"] * baseline - point["actual_kwh"])
            points.append(point)
        updated = {**record, "hourly": points}
        if checked:
            updated["curtailment"] = {
                "hours": hours,
                "lost_kwh": round(lost, 2),
                "lost_kwh_upper": round(lost_upper, 2),
            }
        annotated.append(updated)
    return annotated
