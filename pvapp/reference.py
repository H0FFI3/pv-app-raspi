"""Erzeugung einer lokal zwischengespeicherten PVGIS-TMY-Referenz."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Callable

import pandas as pd

from . import model
from .config import Config, model_fingerprint


def calculate_tmy_reference(
    weather: pd.DataFrame,
    config: Config,
    elevation: float,
    horizon: pd.Series | None = None,
) -> dict:
    """Rechnet einen PVGIS-TMY-Jahresgang mit dem aktuellen AC-Modell."""
    required = {"temp_air", "wind_speed", "ghi", "dni", "dhi"}
    if not required <= set(weather.columns) or weather.empty:
        raise ValueError("PVGIS-TMY enthält nicht alle benötigten Wetterspalten.")
    weather = weather.loc[:, sorted(required)].copy()
    if weather.index.tz is None:
        weather.index = weather.index.tz_localize(config.timezone)
    else:
        weather.index = weather.index.tz_convert(config.timezone)
    hourly = model.estimate_hourly_potential(
        weather,
        elevation,
        config.installed_kwp,
        config,
        horizon,
    )
    daily = hourly.resample("D").sum(min_count=1).dropna()
    by_day: dict[str, list[float]] = {}
    for timestamp, value in daily.items():
        by_day.setdefault(timestamp.strftime("%m-%d"), []).append(float(value))
    expected_daily = {key: round(sum(values) / len(values), 3) for key, values in by_day.items()}
    monthly = {
        month: round(sum(value for key, value in expected_daily.items() if key.startswith(month + "-")), 2)
        for month in (f"{number:02d}" for number in range(1, 13))
    }
    return {
        "model_version": "1",
        "config_hash": model_fingerprint(config),
        "annual_kwh": round(sum(expected_daily.values()), 2),
        "monthly_kwh": monthly,
        "daily_kwh_by_month_day": expected_daily,
    }


def refresh_tmy_reference(
    config: Config,
    cache_path: Path,
    *,
    fetch: Callable[..., tuple[pd.DataFrame, dict]] | None = None,
) -> dict:
    """Ruft PVGIS nur bei ausdrücklichem Aufruf ab und speichert die Referenz atomar."""
    if fetch is None:
        import pvlib

        fetch = pvlib.iotools.get_pvgis_tmy
    weather, metadata = fetch(config.latitude, config.longitude, timeout=30)
    elevation = float(metadata.get("inputs", {}).get("location", {}).get("elevation", 0) or 0)
    if config.horizon_enabled:
        from . import paths, sources

        horizon = sources.load_horizon(config, paths.horizon_cache_path())
    else:
        horizon = None
    reference = calculate_tmy_reference(weather, config, elevation, horizon)
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(reference, stream, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return reference
