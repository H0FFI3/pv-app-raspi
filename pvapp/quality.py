"""Reine Qualitätskennzahlen für AlphaESS-Istwerte."""

from __future__ import annotations

import math


def build_quality(
    *,
    n_samples: int,
    coverage: float,
    integral_kwh: float,
    epv: float,
    hourly: list[dict],
    min_coverage: float = 0.8,
    max_epv_deviation: float = 0.1,
) -> dict:
    """Erzeugt Metadaten und Flags aus Rohproben und dem Tageswert."""
    ratio = integral_kwh / epv if epv > 0 else None
    flags = []
    if coverage < min_coverage:
        flags.append("low_coverage")
    if ratio is not None and abs(ratio - 1) > max_epv_deviation:
        flags.append("epv_mismatch")
    if not hourly or not any(point.get("actual_kwh") is not None for point in hourly):
        flags.append("hourly_missing")
    return {
        "n_samples": int(n_samples),
        "coverage": float(coverage),
        "integral_kwh": float(integral_kwh),
        "integral_ratio": ratio,
        "flags": flags,
    }


def valid_quality(quality: dict) -> dict | None:
    """Validiert ein gespeichertes Qualitätsobjekt für Anzeige und Rückwärtskompatibilität."""
    try:
        n_samples = int(quality["n_samples"])
        coverage = float(quality["coverage"])
        integral_kwh = float(quality["integral_kwh"])
        ratio = quality.get("integral_ratio")
        ratio = None if ratio is None else float(ratio)
        flags = quality.get("flags", [])
        if n_samples < 0 or not 0 <= coverage <= 1 or not math.isfinite(integral_kwh):
            return None
        if ratio is not None and not math.isfinite(ratio):
            return None
        if not isinstance(flags, list) or not all(isinstance(flag, str) for flag in flags):
            return None
        return {
            "n_samples": n_samples,
            "coverage": coverage,
            "integral_kwh": integral_kwh,
            "integral_ratio": ratio,
            "flags": flags,
        }
    except (KeyError, TypeError, ValueError):
        return None
