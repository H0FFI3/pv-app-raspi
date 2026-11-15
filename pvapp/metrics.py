"""Reine Kennzahlen für den Vergleich von Ist-Ertrag und PV-Modell."""

from __future__ import annotations

import math
from collections.abc import Iterable


def calculate_metrics(actual: Iterable[float | None], potential: Iterable[float | None]) -> dict[str, float | int | None]:
    """Berechnet MBE, RMSE, rMBD und MAPE für gepaarte Ist-/Potenzialwerte.

    Fehler sind als ``Potenzial - Ist`` definiert. rMBD normiert den MBE auf
    den mittleren Istwert; MAPE lässt Paare mit Istwert 0 aus.
    """
    pairs = []
    for measured, modeled in zip(actual, potential):
        if measured is None or modeled is None:
            continue
        try:
            measured_value, modeled_value = float(measured), float(modeled)
        except (TypeError, ValueError):
            continue
        if math.isfinite(measured_value) and math.isfinite(modeled_value):
            pairs.append((measured_value, modeled_value))
    if not pairs:
        return {"count": 0, "mbe": None, "rmse": None, "rmbd_pct": None, "mape_pct": None}

    errors = [modeled - measured for measured, modeled in pairs]
    mean_actual = sum(measured for measured, _ in pairs) / len(pairs)
    mape_pairs = [
        abs(modeled - measured) / abs(measured)
        for measured, modeled in pairs
        if measured != 0
    ]
    mbe = sum(errors) / len(errors)
    return {
        "count": len(pairs),
        "mbe": mbe,
        "rmse": math.sqrt(sum(error * error for error in errors) / len(errors)),
        "rmbd_pct": mbe / mean_actual * 100 if mean_actual else None,
        "mape_pct": sum(mape_pairs) / len(mape_pairs) * 100 if mape_pairs else None,
    }


def specific_yield(actual_kwh: float, installed_kwp: float) -> float | None:
    """Spezifischer Ertrag in kWh/kWp."""
    if not math.isfinite(actual_kwh) or not math.isfinite(installed_kwp) or installed_kwp <= 0:
        return None
    return actual_kwh / installed_kwp


def performance_ratio(actual_kwh: float, installed_kwp: float, poa_kwh_m2: float) -> float | None:
    """Performance Ratio als Anteil, mit H_poa in kWh/m²."""
    specific = specific_yield(actual_kwh, installed_kwp)
    if specific is None or not math.isfinite(poa_kwh_m2) or poa_kwh_m2 <= 0:
        return None
    return specific / poa_kwh_m2
