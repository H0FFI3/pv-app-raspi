"""Anzeigedaten für den Bericht aus dem gespeicherten Rohbestand. Leichtgewichtig (kein pandas/pvlib)."""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import date
from pathlib import Path

from . import curtailment, storage
from . import paths
from .completeness import build_completeness
from .config import Config, ConfigError, curtailment_settings_from_env, model_fingerprint

log = logging.getLogger(__name__)


def fallback_curtailment() -> curtailment.CurtailmentSettings:
    """Ohne vollständige Konfiguration (z. B. --offline): Einstellungen aus der Umgebung, sonst Standardwerte."""
    try:
        return curtailment_settings_from_env(os.environ)
    except ConfigError as error:
        log.warning("%s Es gelten die Standardwerte der Abregelungserkennung.", error)
        return curtailment.CurtailmentSettings()


def build_display_records(raw_records: list, config: Config | None) -> list[dict]:
    """Gültige Datensätze ab DATA_START_DATE, mit markierten abgeregelten Stunden."""
    records = storage.valid_records(raw_records, config.data_start_date if config else None)
    return curtailment.annotate_records(records, config.curtailment if config else fallback_curtailment())


def build_dashboard_metadata(raw_records: list, config: Config, today: date) -> dict:
    """Zusatzdaten für Kennzahlen und Vollständigkeitskalender, ohne schwere Abhängigkeiten."""
    completeness = build_completeness(
        raw_records, config.data_start_date, today, config.backfill_max_days
    )
    reference = load_tmy_reference(paths.tmy_cache_path())
    reference_stale = bool(reference and reference["config_hash"] != model_fingerprint(config))
    if reference_stale:
        reference = None
    return {
        "installed_kwp": config.installed_kwp,
        "update_time": config.update_time.strftime("%H:%M"),
        "timezone": config.timezone,
        "tmy_reference": reference,
        "tmy_reference_stale": reference_stale,
        "completeness": completeness,
        "completeness_summary": {
            "missing": sum(item["status"] in {"fehlt", "übersprungen"} for item in completeness),
            "outside_backfill": sum(item["status"] == "übersprungen" for item in completeness),
        },
    }


def load_tmy_reference(path: Path) -> dict | None:
    """Liest die leichte JSON-Referenz ein, ohne die Modellabhängigkeiten zu laden."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        log.warning("PVGIS-TMY-Cache ist nicht lesbar: %s", error)
        return None
    if not isinstance(value, dict) or not isinstance(value.get("daily_kwh_by_month_day"), dict):
        log.warning("PVGIS-TMY-Cache hat ein ungültiges Format.")
        return None
    daily = {}
    for key, amount in value["daily_kwh_by_month_day"].items():
        try:
            number = float(amount)
        except (TypeError, ValueError):
            continue
        if isinstance(key, str) and len(key) == 5 and key[2] == "-" and number >= 0 and math.isfinite(number):
            daily[key] = number
    if not daily:
        return None
    return {"config_hash": value.get("config_hash"), "daily_kwh_by_month_day": daily}
