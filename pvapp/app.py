"""Ablauf der App: Historie laden, fehlende Tage erfassen (Backfill), Bericht erzeugen und öffnen."""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import logging
import os
import sqlite3
import sys
import tempfile
import webbrowser
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import pandas as pd

from . import db, model, paths, sources, storage
from .config import MODEL_VERSION, Config, ConfigError, load_config, model_fingerprint
from .display import build_dashboard_metadata, build_display_records
from .interactive import chooser_for_terminal, is_interactive, prompt_credentials
from .logging_setup import REDACTOR, setup_logging
from .reference import refresh_tmy_reference
from .report import create_standalone_report, resolve_report_path

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- Planung


@dataclass
class CollectionPlan:
    days: list[date] = field(default_factory=list)  # neu bzw. vollständig neu zu erfassen
    signal_days: list[date] = field(default_factory=list)  # nur Akku-/Netzsignale nachladen (Tag bleibt sonst unverändert)
    upgrade_days: list[date] = field(default_factory=list)  # Forecast-Wetter durch vollständiges Archiv ersetzen
    before_start: bool = False  # gestern liegt noch vor DATA_START_DATE
    skipped_older: int = 0  # fehlende Tage außerhalb des Backfill-Fensters
    up_to_date: bool = False


def plan_days(
    stored: set[date],
    today: date,
    data_start: date,
    max_days: int,
    refresh: bool = False,
    *,
    refresh_days: int = 0,
    signal_candidates: set[date] | frozenset[date] = frozenset(),
    upgrade_candidates: set[date] | frozenset[date] = frozenset(),
    upgrade_after_days: int = 0,
) -> CollectionPlan:
    """Bestimmt, was erfasst wird.

    - Alle fehlenden Tage zwischen DATA_START_DATE und gestern, höchstens die letzten ``max_days``.
    - ``refresh`` bzw. ``refresh_days``: zusätzlich die letzten N Tage (gespeicherte) neu abrufen.
    - ``signal_candidates``: gespeicherte Tage ohne Akku-/Netzsignale; nur deren Signale werden nachgeladen
      (ebenfalls begrenzt auf das Fenster der letzten ``max_days`` Tage).
    """
    yesterday = today - timedelta(days=1)
    if yesterday < data_start:
        return CollectionPlan(before_start=True)
    span = (yesterday - data_start).days + 1
    missing = [data_start + timedelta(days=i) for i in range(span) if (data_start + timedelta(days=i)) not in stored]
    refresh_days = max(refresh_days, 1 if refresh else 0)
    for offset in range(refresh_days):
        day = yesterday - timedelta(days=offset)
        if day >= data_start and day in stored:
            missing.append(day)
    missing = sorted(set(missing))
    skipped = max(0, len(missing) - max_days)
    days = missing[-max_days:] if missing else []

    window_start = yesterday - timedelta(days=max_days - 1)
    signal_days = sorted(d for d in signal_candidates if window_start <= d <= yesterday and d not in days)
    upgrade_days = []
    if upgrade_after_days > 0:
        upgrade_days = sorted(
            day for day in upgrade_candidates
            if window_start <= day <= yesterday
            and (today - day).days >= upgrade_after_days
            and day not in days
        )
    return CollectionPlan(
        days=days,
        signal_days=signal_days,
        upgrade_days=upgrade_days,
        skipped_older=skipped,
        up_to_date=not days and not signal_days and not upgrade_days,
    )


# ------------------------------------------------------------------------- Erfassung


@dataclass
class CollectionResult:
    records: list[dict] = field(default_factory=list)
    skipped: dict[date, str] = field(default_factory=dict)


async def collect_records(
    config: Config,
    days: list[date],
    *,
    include_hourly: bool = True,
    chooser: Callable[[list[dict]], dict] | None = None,
    load_weather_fn: Callable[..., sources.WeatherData] = sources.load_weather,
    fetch_actuals_fn: Callable[..., Any] = sources.fetch_actuals,
    load_horizon_fn: Callable[..., pd.Series | None] = sources.load_horizon,
    upgrade_days: list[date] | None = None,
    stored_records: dict[date, dict] | None = None,
    raw_data_callback: Callable[[str, date | None, Any], None] | None = None,
) -> CollectionResult:
    """Erfasst Datensätze für ``days``. Einzelne Tage ohne Daten werden übersprungen (nicht der ganze Lauf)."""
    result = CollectionResult()
    upgrade_days = sorted(set(upgrade_days or ()) - set(days))
    stored_records = stored_records or {}
    if not days and not upgrade_days:
        return result
    days = sorted(days)
    all_days = sorted(set(days) | set(upgrade_days))

    log.info("Wetter: rufe Strahlungs- und Sonnenscheindaten ab ...")
    weather_callback = (
        {"raw_data_callback": raw_data_callback}
        if raw_data_callback is not None and load_weather_fn is sources.load_weather
        else {}
    )
    weather = load_weather_fn(config, all_days[0], all_days[-1], **weather_callback)
    computable = []
    for day in all_days:
        if day in weather.source_by_day:
            if day in upgrade_days and weather.source_by_day[day] != "archive":
                result.skipped[day] = "Archivdaten sind noch nicht vollständig verfügbar"
            else:
                computable.append(day)
        else:
            result.skipped[day] = "Wetterdaten sind noch nicht vollständig verfügbar"
    if not computable:
        return result

    actual_days = [day for day in computable if day not in upgrade_days]
    actual_callback = (
        {"raw_data_callback": raw_data_callback}
        if raw_data_callback is not None and fetch_actuals_fn is sources.fetch_actuals
        else {}
    )
    actual = (
        await fetch_actuals_fn(
            config, actual_days, include_hourly=include_hourly, chooser=chooser, **actual_callback
        )
        if actual_days else None
    )

    log.info("Modell: berechne das wetterbasierte PV-Potenzial ...")
    horizon = load_horizon_fn(config, paths.horizon_cache_path()) if config.horizon_enabled else None
    computed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    provenance = {
        "config_hash": model_fingerprint(config),
        "model_version": MODEL_VERSION,
        "computed_at": computed_at,
    }
    normal_wall_potential = None
    normal_poa = None
    if actual is not None:
        normal_potential = model.estimate_hourly_potential(
            weather.frame, weather.elevation, actual.inverter_power_kw, config, horizon
        )
        normal_wall_potential = model.hourly_wall_clock(normal_potential)
        normal_poa = model.estimate_hourly_poa(weather.frame, weather.elevation, config, horizon)

    for day in computable:
        previous = stored_records.get(day, {})
        if day in upgrade_days:
            inverter_power_kw = float(previous.get("inverter_power_kw") or config.installed_kwp)
            day_weather = weather.frame[weather.frame.index.date == day]
            hourly_potential = model.estimate_hourly_potential(
                day_weather, weather.elevation, inverter_power_kw, config, horizon
            )
            wall_potential = model.hourly_wall_clock(hourly_potential)
            day_poa = model.estimate_hourly_poa(day_weather, weather.elevation, config, horizon)
            measured = {}
            signals = {}
        else:
            assert actual is not None and normal_wall_potential is not None
            assert normal_poa is not None
            if day in actual.errors:
                result.skipped[day] = actual.errors[day]
                continue
            wall_potential = normal_wall_potential
            day_poa = normal_poa[normal_poa.index.date == day]
            measured = actual.hourly.get(day, {})
            signals = actual.signals.get(day, {})
        wall_days = wall_potential.index.date
        day_hours = wall_potential[wall_days == day].dropna()
        if day_hours.empty:
            result.skipped[day] = "Für den Tag konnte kein Potenzial berechnet werden"
            continue
        profile = []
        for timestamp, value in day_hours.items():
            label = timestamp.strftime("%H:00")
            point = {"hour": label, "actual_kwh": measured.get(label), "potential_kwh": round(float(value), 3)}
            point.update(signals.get(label, {}))  # soc_pct / feed_in_w, soweit AlphaESS sie liefert
            profile.append(point)
        if day in upgrade_days:
            new_potential_by_hour = {point["hour"]: point["potential_kwh"] for point in profile}
            upgraded_profile = [
                {
                    **point,
                    "potential_kwh": new_potential_by_hour.get(point.get("hour"), point["potential_kwh"]),
                }
                for point in previous.get("hourly", [])
            ]
            result.records.append({
                **previous,
                "potential_kwh": round(float(day_hours.sum()), 2),
                "sunshine_hours": round(weather.sunshine_hours[day], 2),
                "weather_source": "archive",
                "hourly": upgraded_profile if previous.get("hourly") else previous.get("hourly", []),
                "poa_kwh_m2": round(float(day_poa.sum()), 3),
                **provenance,
            })
        else:
            assert actual is not None
            record = {
                "date": day.isoformat(),
                "actual_kwh": round(actual.energy[day], 2),
                "potential_kwh": round(float(day_hours.sum()), 2),
                "sunshine_hours": round(weather.sunshine_hours[day], 2),
                "weather_source": weather.source_by_day[day],
                "inverter_power_kw": actual.inverter_power_kw,
                "hourly": profile,
                "poa_kwh_m2": round(float(day_poa[day_poa.index.date == day].sum()), 3),
                **provenance,
            }
            if day in actual.quality:
                record["quality"] = actual.quality[day]
            result.records.append(record)
            if day in actual.signals:  # Leistungsdaten wurden erfolgreich abgerufen (auch wenn ohne Akku-/Netzfelder)
                result.records[-1]["signals_checked"] = True
    return result


async def collect_signals(
    config: Config,
    days: list[date],
    *,
    chooser: Callable[[list[dict]], dict] | None = None,
    fetch_actuals_fn: Callable[..., Any] = sources.fetch_actuals,
    raw_data_callback: Callable[[str, date | None, Any], None] | None = None,
) -> dict[date, dict[str, dict[str, float]]]:
    """Lädt nur die Akku-/Netzsignale für bereits gespeicherte Tage. Rückgabe: Tag -> Stunde -> Signale,
    nur für Tage, deren Leistungsdaten erfolgreich abgerufen wurden (Ergebnis kann leer sein)."""
    if not days:
        return {}
    callback = (
        {"raw_data_callback": raw_data_callback}
        if raw_data_callback is not None and fetch_actuals_fn is sources.fetch_actuals
        else {}
    )
    actual = await fetch_actuals_fn(
        config, sorted(days), include_hourly=True, chooser=chooser, **callback
    )
    return {day: actual.signals[day] for day in days if day in actual.signals}


def _stored_weather_for_day(repository: db.Repository, day: date, config: Config, preferred_source: str):
    """Rebuilds a single day's source frame from UTC rows already stored in SQLite."""
    zone = ZoneInfo(config.timezone)
    start = datetime.combine(day, time.min, tzinfo=zone).astimezone(timezone.utc) - timedelta(days=1)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone).astimezone(timezone.utc) + timedelta(days=1)
    rows = repository.weather_hours(start.isoformat(), end.isoformat())
    source_order = [preferred_source, "archive", "forecast"]
    for source in dict.fromkeys(source_order):
        source_rows = [row for row in rows if row["source"] == source]
        if not source_rows:
            continue
        index = pd.DatetimeIndex(pd.to_datetime([row["ts_utc"] for row in source_rows], utc=True))
        index = (index - pd.Timedelta(minutes=30)).tz_convert(config.timezone)
        frame = pd.DataFrame(
            {
                name: [row[field] for row in source_rows]
                for name, field in (
                    ("temp_air", "temp_air"),
                    ("wind_speed", "wind_speed"),
                    ("ghi", "ghi"),
                    ("dni", "dni"),
                    ("dhi", "dhi"),
                )
            },
            index=index,
        ).dropna()
        sunshine = pd.Series(
            [row["sunshine_s"] for row in source_rows],
            index=index,
            dtype=float,
        ).dropna()
        day_frame = frame[frame.index.date == day]
        day_sunshine = sunshine[sunshine.index.date == day]
        if sources.complete_days(day_frame.index) != {day} or sources.complete_days(day_sunshine.index) != {day}:
            continue
        elevation = next((row["elevation"] for row in source_rows if row["elevation"] is not None), 0.0)
        return day_frame, float(elevation)
    return None


def recompute_history(
    payload: dict,
    config: Config,
    repository: db.Repository,
    *,
    start_day: date | None = None,
    end_day: date | None = None,
    run_summary: dict | None = None,
) -> bool:
    """Berechnet gespeicherte Potenziale aus SQLite-Wetter neu, ohne AlphaESS-Aufrufe."""
    records = [record for record in payload.get("records", []) if isinstance(record, dict)]
    dated_records = []
    for record in records:
        try:
            day = date.fromisoformat(record["date"])
        except (KeyError, TypeError, ValueError):
            continue
        if (start_day is None or day >= start_day) and (end_day is None or day <= end_day):
            dated_records.append((day, record))
    if not dated_records:
        log.info("Im gewählten Zeitraum gibt es keine Tagesdatensätze zum Neuberechnen.")
        return False

    horizon = sources.load_horizon(config, paths.horizon_cache_path()) if config.horizon_enabled else None
    provenance = {
        "config_hash": model_fingerprint(config),
        "model_version": MODEL_VERSION,
        "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    changed = False
    for day, record in dated_records:
        cached = _stored_weather_for_day(repository, day, config, record.get("weather_source", ""))
        if cached is None:
            log.warning("Neuberechnung für %s übersprungen: keine vollständigen gespeicherten Wetterstunden.", day)
            continue
        weather, elevation = cached
        inverter_power_kw = float(record.get("inverter_power_kw") or config.installed_kwp)
        hourly = model.hourly_wall_clock(
            model.estimate_hourly_potential(weather, elevation, inverter_power_kw, config, horizon)
        )
        potentials = {timestamp.strftime("%H:00"): round(float(value), 3) for timestamp, value in hourly.items()}
        previous_hourly = record.get("hourly")
        if isinstance(previous_hourly, list) and previous_hourly:
            seen = set()
            updated_hourly = []
            for point in previous_hourly:
                if not isinstance(point, dict):
                    continue
                label = str(point.get("hour", ""))
                if label in potentials:
                    point = {**point, "potential_kwh": potentials[label]}
                    seen.add(label)
                updated_hourly.append(point)
            updated_hourly.extend(
                {"hour": label, "actual_kwh": None, "potential_kwh": value}
                for label, value in potentials.items()
                if label not in seen
            )
        else:
            updated_hourly = [
                {"hour": label, "actual_kwh": None, "potential_kwh": value}
                for label, value in potentials.items()
            ]
        poa = model.estimate_hourly_poa(weather, elevation, config, horizon)
        replacement = {
            **record,
            "potential_kwh": round(float(hourly.sum()), 2),
            "hourly": updated_hourly,
            "poa_kwh_m2": round(float(poa.sum()), 3),
            **provenance,
        }
        if replacement != record:
            payload["records"] = storage.upsert_record(payload["records"], replacement)
            changed = True
            if run_summary is not None:
                run_summary["days_ok"] = run_summary.get("days_ok", 0) + 1
            log.info("Potenzial mit gespeicherten Wetterdaten neu berechnet: %s.", day.isoformat())
    return changed


# ------------------------------------------------------------------------------ CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=paths.APP_NAME,
        description="Erfasst PV-Tageswerte und öffnet den lokalen HTML-Bericht.",
    )
    parser.add_argument("--offline", action="store_true", help="Nur vorhandene lokale Daten anzeigen (kein Abruf).")
    parser.add_argument("--refresh", action="store_true", help="Den Vortag auch dann neu abrufen, wenn er schon gespeichert ist.")
    parser.add_argument("--refresh-days", type=int, metavar="N", help="Die letzten N Tage neu abrufen (1 bis 92), auch wenn sie schon gespeichert sind.")
    parser.add_argument("--recompute", action="store_true", help="Gespeicherte Potenziale aus lokalen Wetterdaten neu berechnen (ohne AlphaESS-Abruf).")
    parser.add_argument("--from", dest="recompute_from", type=date.fromisoformat, metavar="DATUM", help="Frühester Tag für --recompute (JJJJ-MM-TT).")
    parser.add_argument("--to", dest="recompute_to", type=date.fromisoformat, metavar="DATUM", help="Letzter Tag für --recompute (JJJJ-MM-TT).")
    parser.add_argument("--no-open", action="store_true", help="Bericht erzeugen, aber nicht im Browser öffnen (z. B. für Aufgabenplanung).")
    parser.add_argument("--no-report", action="store_true", help="Keine HTML-Datei schreiben (der Server liefert den Bericht selbst aus).")
    parser.add_argument("--log-file", type=Path, metavar="DATEI", help="Meldungen zusätzlich in diese Datei schreiben (vom Server genutzt).")
    parser.add_argument("--verbose", action="store_true", help="Ausführliche Protokollierung.")
    return parser


def _try_config() -> tuple[Config | None, str | None]:
    try:
        config = load_config()
    except ConfigError as error:
        return None, str(error)
    REDACTOR.add(*config.secrets)
    return config, None


def update_history(
    payload: dict,
    config: Config,
    options: argparse.Namespace,
    *,
    raw_data_callback: Callable[[str, date | None, Any], None] | None = None,
    run_summary: dict | None = None,
) -> bool:
    """Erfasst fehlende Tage und aktualisiert ``payload['records']``. Gibt zurück, ob sich etwas geändert hat."""
    today = sources.local_today(config.timezone)
    refresh_days = options.refresh_days or 0
    if not 0 <= refresh_days <= 92:
        raise ConfigError("--refresh-days erwartet eine Zahl von 1 bis 92.")
    plan = plan_days(
        storage.stored_dates(payload["records"]),
        today,
        config.data_start_date,
        config.backfill_max_days,
        refresh=options.refresh,
        refresh_days=refresh_days,
        signal_candidates=storage.days_missing_signals(payload["records"]) if config.curtailment.enabled else frozenset(),
        upgrade_candidates={
            date.fromisoformat(record["date"])
            for record in storage.valid_records(payload["records"])
            if record.get("weather_source") == "forecast"
        },
        upgrade_after_days=config.weather_upgrade_after_days,
    )
    if run_summary is not None:
        run_summary["days_skipped_older"] = plan.skipped_older
    if plan.before_start:
        first_full = config.data_start_date + timedelta(days=1)
        log.info("Die Erfassung beginnt am %s.", config.data_start_date.strftime("%d.%m.%Y"))
        log.info("Der erste vollständige Tagesdatensatz ist am %s verfügbar.", first_full.strftime("%d.%m.%Y"))
        return False
    if plan.up_to_date:
        log.info("Alle Tage bis gestern sind bereits gespeichert; kein Abruf nötig.")
        return False
    if plan.skipped_older:
        log.warning(
            "%d ältere fehlende Tage werden nicht nachgeholt (Backfill-Fenster: %d Tage, BACKFILL_MAX_DAYS).",
            plan.skipped_older,
            config.backfill_max_days,
        )

    config = prompt_credentials(config)
    REDACTOR.add(*config.secrets)
    if plan.days:
        log.info(
            "Datenabruf für %s wird gestartet.",
            ", ".join(day.isoformat() for day in plan.days) if len(plan.days) <= 3 else f"{len(plan.days)} Tage ({plan.days[0]} bis {plan.days[-1]})",
        )
    if plan.signal_days:
        log.info(
            "Akku-/Netzdaten für die Abregelungserkennung werden für %d bereits gespeicherte Tage nachgeladen (%s).",
            len(plan.signal_days),
            ", ".join(day.isoformat() for day in plan.signal_days),
        )
    if plan.upgrade_days:
        log.info(
            "Forecast-Wetter wird für %d ältere Tage auf vollständige Archivdaten geprüft.",
            len(plan.upgrade_days),
        )

    async def gather():
        collected = (
            await collect_records(
                config,
                plan.days,
                chooser=chooser_for_terminal(),
                upgrade_days=plan.upgrade_days,
                stored_records={
                    date.fromisoformat(record["date"]): record
                    for record in payload["records"]
                    if isinstance(record, dict) and isinstance(record.get("date"), str)
                },
                raw_data_callback=raw_data_callback,
            )
            if plan.days or plan.upgrade_days
            else CollectionResult()
        )
        if plan.days and plan.signal_days:
            await asyncio.sleep(config.api_request_interval_seconds)  # API-Schutzpause zwischen zwei Anmeldungen
        signals = (
            await collect_signals(
                config, plan.signal_days, chooser=chooser_for_terminal(),
                raw_data_callback=raw_data_callback,
            )
            if plan.signal_days else {}
        )
        return collected, signals

    result, signal_result = asyncio.run(gather())
    if run_summary is not None:
        run_summary["days_ok"] = len(result.records)
        run_summary["skipped_days"] = [
            {"date": day.isoformat(), "reason": REDACTOR.redact(reason)}
            for day, reason in sorted(result.skipped.items())
        ]
        run_summary["signals_updated"] = len(signal_result)
        run_summary["weather_upgrades"] = sum(
            date.fromisoformat(record["date"]) in plan.upgrade_days for record in result.records
        )

    for record in result.records:
        payload["records"] = storage.upsert_record(payload["records"], record)
        if date.fromisoformat(record["date"]) in plan.upgrade_days:
            log.info("Archiv-Umstellung durchgeführt: %s (Wetterquelle: %s).", record["date"], record["weather_source"])
        else:
            log.info(
                "Erfasst: %s | Ist %.2f kWh | Potenzial %.2f kWh | Sonne %.2f h (Wetter: %s)",
                record["date"],
                record["actual_kwh"],
                record["potential_kwh"],
                record["sunshine_hours"],
                record["weather_source"],
            )
    for day, reason in sorted(result.skipped.items()):
        if day in plan.upgrade_days:
            log.info("Archiv-Umstellung für %s noch nicht möglich: %s.", day.isoformat(), reason)
        else:
            log.warning("Übersprungen: %s – %s. Beim nächsten Start wird es erneut versucht.", day.isoformat(), reason)

    for day, signals in sorted(signal_result.items()):
        payload["records"] = storage.apply_signals(payload["records"], day, signals)
        if signals:
            log.info("Akku-/Netzdaten nachgeladen: %s (%d Stunden mit Signalen).", day.isoformat(), len(signals))
        else:
            log.warning("AlphaESS liefert für %s keine Akku-/Netzdaten mehr; der Tag wird nicht erneut abgefragt.", day.isoformat())
    for day in sorted(set(plan.signal_days) - set(signal_result)):
        log.warning("Nachladen für %s nicht möglich; beim nächsten Start wird es erneut versucht.", day.isoformat())
    return bool(result.records) or bool(signal_result)


def _write_run_summary(summary: dict) -> None:
    path = paths.last_run_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(summary, stream, ensure_ascii=False, indent=2)
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


def run(options: argparse.Namespace) -> int:
    log.info("PV-Tagesbericht wird gestartet.")
    run_started = datetime.now(timezone.utc)
    run_summary = {
        "started_at": run_started.isoformat(timespec="seconds"),
        "days_ok": 0,
        "days_skipped_older": 0,
        "skipped_days": [],
        "signals_updated": 0,
        "weather_upgrades": 0,
        "data_api_calls": 0,
        "error_classes": [],
    }
    if (options.recompute_from or options.recompute_to) and not options.recompute:
        raise ConfigError("--from und --to sind nur zusammen mit --recompute zulässig.")
    if options.recompute_from and options.recompute_to and options.recompute_from > options.recompute_to:
        raise ConfigError("--from darf nicht nach --to liegen.")
    if options.offline and options.recompute:
        raise ConfigError("--offline und --recompute können nicht kombiniert werden.")
    data_path = paths.data_path()
    repository = db.Repository(paths.database_path())
    try:
        repository.initialize(data_path)
    except (OSError, sqlite3.Error, RuntimeError) as error:
        log.warning("SQLite-Datenbank nicht verfügbar; verwende daily.json (%s).", error)
        repository = None
    payload = storage.load_payload(data_path)
    original = copy.deepcopy(payload)
    log.info("%d lokale Tagesdatensätze geladen.", len(payload["records"]))
    data_api_calls = 0

    def persist_raw_data(kind: str, day: date | None, value: Any) -> None:
        nonlocal data_api_calls
        data_api_calls += 1
        if repository:
            repository.persist_callback(kind, day, value)

    config, config_error = _try_config()
    exit_code = 0
    if options.recompute:
        if config is None:
            log.error("Neuberechnung nicht möglich: %s", config_error)
            exit_code = 1
            run_summary["error_classes"].append("Konfiguration")
        elif repository is None:
            log.error("Neuberechnung nicht möglich: Die SQLite-Datenbank ist nicht verfügbar.")
            exit_code = 1
            run_summary["error_classes"].append("SQLite")
        else:
            try:
                recompute_history(
                    payload,
                    config,
                    repository,
                    start_day=options.recompute_from,
                    end_day=options.recompute_to,
                    run_summary=run_summary,
                )
            except Exception as error:
                log.error("Neuberechnung fehlgeschlagen: %s", error)
                log.debug("Details", exc_info=True)
                exit_code = 1
                run_summary["error_classes"].append(type(error).__name__)
    elif options.offline:
        if config_error:
            log.info("Konfiguration unvollständig; es werden alle gespeicherten Datensätze angezeigt.")
    elif config is None:
        log.error("Aktualisierung fehlgeschlagen: %s", config_error)
        log.info("Der Bericht wird mit den zuletzt lokal gespeicherten Daten geöffnet.")
        exit_code = 1
        run_summary["error_classes"].append("Konfiguration")
    else:
        try:
            refresh_tmy_reference(config, paths.tmy_cache_path())
            log.info("PVGIS-TMY-Referenz aktualisiert.")
        except Exception as error:
            log.warning("PVGIS-TMY-Referenz konnte nicht aktualisiert werden: %s", error)
            log.debug("Details zur PVGIS-TMY-Aktualisierung", exc_info=True)
        has_credentials = bool(config.alphaess_app_id and config.alphaess_app_secret)
        log.info(
            "AlphaESS-Zugangsdaten gefunden; Werte werden nicht angezeigt."
            if has_credentials
            else "AlphaESS-Zugangsdaten fehlen oder sind unvollständig."
        )
        try:
            update_history(
                payload, config, options,
                raw_data_callback=persist_raw_data,
                run_summary=run_summary,
            )
        except Exception as error:  # Netzwerk-, API- oder Modellfehler: mit lokalen Daten weiterarbeiten
            log.error("Aktualisierung fehlgeschlagen: %s", error)
            log.debug("Details", exc_info=True)
            log.info("Der Bericht wird mit den zuletzt lokal gespeicherten Daten geöffnet.")
            exit_code = 1
            run_summary["error_classes"].append(type(error).__name__)

    if payload != original:
        storage.save_payload(payload, data_path)
        if repository:
            try:
                repository.upsert_daily_records(payload["records"])
            except (OSError, sqlite3.Error, RuntimeError):
                log.warning("Tagesdatensätze konnten nicht zusätzlich in SQLite gespeichert werden.")

    if not options.offline:
        run_finished = datetime.now(timezone.utc)
        run_summary["data_api_calls"] = data_api_calls
        run_summary["finished_at"] = run_finished.isoformat(timespec="seconds")
        run_summary["duration_seconds"] = max(0.0, (run_finished - run_started).total_seconds())
        run_summary["ok"] = exit_code == 0
        try:
            _write_run_summary(run_summary)
        except OSError as error:
            log.warning("Laufzusammenfassung konnte nicht gespeichert werden: %s", error)

    display = build_display_records(payload["records"], config)
    flagged = sum(r.get("curtailment", {}).get("hours", 0) for r in display)
    if flagged:
        log.info("Abregelung: %d Stunde(n) in der Historie als wahrscheinlich abgeregelt markiert.", flagged)
    log.info("Lokale Daten: %s", data_path)
    if options.no_report:
        return exit_code
    log.info("Erzeuge eigenständigen HTML-Bericht ...")
    report_path = resolve_report_path(config.report_path if config else None, paths.app_directory(), paths.app_data_directory())
    metadata = (
        build_dashboard_metadata(payload["records"], config, sources.local_today(config.timezone))
        if config
        else {}
    )
    create_standalone_report(display, paths.resource_root(), report_path, metadata)
    log.info("HTML-Bericht erstellt: %s", report_path)
    if not options.no_open:
        log.info("Öffne Bericht im Standardbrowser ...")
        if not webbrowser.open(report_path.resolve().as_uri()):
            log.warning("Browser konnte nicht gestartet werden. Datei manuell öffnen: %s", report_path)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    options = build_parser().parse_args(argv)
    setup_logging(paths.log_directory(), verbose=options.verbose, extra_log_file=options.log_file)
    exit_code = 1
    try:
        exit_code = run(options)
    except Exception:  # Unerwartet: sichtbar machen, nicht still schließen
        log.exception("Unerwarteter Fehler. Details stehen in der Logdatei: %s", paths.log_directory())
    if is_interactive() and not options.no_open:
        try:
            input("Eingabetaste zum Schließen drücken ...")
        except EOFError:
            pass
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
