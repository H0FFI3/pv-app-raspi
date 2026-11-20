"""Vergleicht Archiv-, Forecast- und Satellitenstrahlung mit gespeicherten Iststunden.

Die Satellite Radiation API ist regional und historisch nicht durchgehend verfügbar.
Dokumentation: https://open-meteo.com/en/docs/satellite-radiation-api
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pvapp import model, paths, sources, storage  # noqa: E402
from pvapp.config import load_config  # noqa: E402
from pvapp.display import build_display_records  # noqa: E402
from pvapp.metrics import calculate_metrics  # noqa: E402

SATELLITE_URL = "https://satellite-api.open-meteo.com/v1/archive"


def satellite_weather(
    config,
    start: date,
    end: date,
    temperature_frame: pd.DataFrame,
    *,
    http_get: Callable[..., Any] | None = None,
) -> pd.DataFrame:
    """Lädt Satellitenstrahlung und verbindet sie mit Archivtemperatur/-wind."""
    params = {
        "latitude": config.latitude,
        "longitude": config.longitude,
        "start_date": (start - timedelta(days=1)).isoformat(),
        "end_date": (end + timedelta(days=1)).isoformat(),
        "hourly": "shortwave_radiation,direct_normal_irradiance,diffuse_radiation",
        "timeformat": "unixtime",
        "timezone": "UTC",
        "models": "satellite_radiation_seamless",
    }
    payload = sources.fetch_json(SATELLITE_URL, params, http_get=http_get)
    hourly = payload["hourly"]
    index = (pd.to_datetime(hourly["time"], unit="s", utc=True) - pd.Timedelta(minutes=30)).tz_convert(config.timezone)
    radiation = pd.DataFrame(
        {
            "ghi": hourly["shortwave_radiation"],
            "dni": hourly["direct_normal_irradiance"],
            "dhi": hourly["diffuse_radiation"],
        },
        index=index,
    )
    return radiation.join(temperature_frame[["temp_air", "wind_speed"]], how="inner").dropna()


def compare_records(records: list[dict], config, start: date, end: date, *, http_get=None) -> dict[str, dict]:
    """Vergleicht nur gespeicherte Iststunden, die nicht als abgeregelt markiert sind."""
    days = [
        date.fromisoformat(record["date"])
        for record in records
        if start <= date.fromisoformat(record["date"]) <= end
    ]
    if not days:
        return {name: calculate_metrics([], []) for name in ("archive", "forecast", "satellite")}
    archive = sources.load_weather(config, min(days), max(days), source="archive", http_get=http_get)
    satellite = satellite_weather(config, min(days), max(days), archive.frame, http_get=http_get)
    weather_by_source = {
        "archive": archive.frame,
        "forecast": sources.load_weather(config, min(days), max(days), source="forecast", http_get=http_get).frame,
        "satellite": satellite,
    }
    horizon = sources.load_horizon(config, paths.horizon_cache_path()) if config.horizon_enabled else None
    results: dict[str, dict] = {}
    for name, frame in weather_by_source.items():
        actual_values, modeled_values = [], []
        for record in records:
            day = date.fromisoformat(record["date"])
            if not start <= day <= end:
                continue
            day_weather = frame[frame.index.date == day]
            if day_weather.empty:
                continue
            inverter = float(record.get("inverter_power_kw") or config.installed_kwp)
            modeled = model.hourly_wall_clock(
                model.estimate_hourly_potential(day_weather, archive.elevation, inverter, config, horizon)
            )
            points = {point.get("hour"): point for point in record.get("hourly", [])}
            for timestamp, potential in modeled.items():
                point = points.get(timestamp.strftime("%H:00"))
                if not point or point.get("actual_kwh") is None or point.get("curtailed"):
                    continue
                actual_values.append(point["actual_kwh"])
                modeled_values.append(float(potential))
        results[name] = calculate_metrics(actual_values, modeled_values)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", type=date.fromisoformat, required=True, metavar="JJJJ-MM-TT")
    parser.add_argument("--to", dest="end", type=date.fromisoformat, required=True, metavar="JJJJ-MM-TT")
    options = parser.parse_args(argv)
    if options.end < options.start:
        parser.error("--to darf nicht vor --from liegen.")
    config = load_config()
    payload = storage.load_payload(paths.data_path())
    records = build_display_records(payload["records"], config)
    try:
        results = compare_records(records, config, options.start, options.end)
    except sources.SourceError as error:
        parser.exit(1, f"Strahlungsquellen konnten nicht verglichen werden: {error}\n")
    print("Quelle       n   MBE kWh   RMSE kWh   rMBD %   MAPE %")
    for name, metrics in results.items():
        print(
            f"{name:<10} {metrics['count']:>4} "
            f"{_format_metric(metrics['mbe']):>9} {_format_metric(metrics['rmse']):>10} "
            f"{_format_metric(metrics['rmbd_pct']):>8} {_format_metric(metrics['mape_pct']):>8}"
        )
    print("Nur Auswertung: Die Produktiv-Wetterquelle wird nicht geändert.")
    return 0


def _format_metric(value) -> str:
    return "-" if value is None else f"{value:.2f}"


if __name__ == "__main__":
    raise SystemExit(main())
