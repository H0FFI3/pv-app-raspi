"""Dauerhafte Speicherung der Tagesdaten und Rohantworten in SQLite."""

from __future__ import annotations

import json
import logging
import math
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from . import storage

log = logging.getLogger(__name__)

SCHEMA_VERSION = 4


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


class Repository:
    """SQLite-Repository. Rohantworten werden unverändert als JSON mitgespeichert."""

    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self, legacy_path: Path | None = None) -> None:
        """Legt Tabellen an, migriert das Schema und importiert daily.json einmalig."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError("Die SQLite-Datenbank stammt aus einer neueren App-Version.")
            if version < 1:
                statements = (
                    """CREATE TABLE daily (
                        day TEXT PRIMARY KEY,
                        raw_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )""",
                    """CREATE TABLE daily_energy (
                        day TEXT PRIMARY KEY,
                        raw_json TEXT NOT NULL,
                        epv REAL,
                        fetched_at TEXT NOT NULL
                    )""",
                    """CREATE TABLE power_samples (
                        day TEXT NOT NULL,
                        ts TEXT NOT NULL,
                        ppv REAL,
                        cbat REAL,
                        feed_in REAL,
                        raw_json TEXT NOT NULL,
                        fetched_at TEXT NOT NULL,
                        PRIMARY KEY(day, ts)
                    )""",
                    """CREATE TABLE weather_hourly (
                        ts_utc TEXT NOT NULL,
                        source TEXT NOT NULL,
                        temp_air REAL,
                        wind_speed REAL,
                        ghi REAL,
                        dni REAL,
                        dhi REAL,
                        sunshine_s REAL,
                        fetched_at TEXT NOT NULL,
                        PRIMARY KEY(ts_utc, source)
                    )""",
                )
                for statement in statements:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version = 1")
                version = 1
            if version < 2:
                connection.execute(
                    "CREATE TABLE legacy_payload (id INTEGER PRIMARY KEY CHECK(id = 1), raw_json TEXT NOT NULL)"
                )
                connection.execute(
                    "CREATE TABLE migration_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                connection.execute("PRAGMA user_version = 2")
                version = 2
            if version < 3:
                connection.execute(
                    "ALTER TABLE weather_hourly ADD COLUMN raw_json TEXT NOT NULL DEFAULT '{}'"
                )
                connection.execute("PRAGMA user_version = 3")
                version = 3
            if version < 4:
                connection.execute(
                    "ALTER TABLE weather_hourly ADD COLUMN elevation REAL"
                )
                connection.execute("PRAGMA user_version = 4")
        if legacy_path is not None and Path(legacy_path).exists():
            self._import_legacy(Path(legacy_path))

    def _import_legacy(self, legacy_path: Path) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            imported = connection.execute(
                "SELECT 1 FROM migration_state WHERE key = 'daily_json_imported'"
            ).fetchone()
            if imported:
                return
        payload = storage.load_payload(legacy_path)
        imported_at = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            imported = connection.execute(
                "SELECT 1 FROM migration_state WHERE key = 'daily_json_imported'"
            ).fetchone()
            if imported:
                return
            connection.execute(
                "INSERT OR REPLACE INTO legacy_payload(id, raw_json) VALUES (1, ?)",
                (_json(payload),),
            )
            for record in payload.get("records", []):
                if not isinstance(record, dict):
                    continue
                day = record.get("date")
                try:
                    date.fromisoformat(day)
                except (TypeError, ValueError):
                    continue
                connection.execute(
                    "INSERT OR IGNORE INTO daily(day, raw_json, updated_at) VALUES (?, ?, ?)",
                    (day, _json(record), imported_at),
                )
            connection.execute(
                "INSERT INTO migration_state(key, value) VALUES ('daily_json_imported', ?)",
                (imported_at,),
            )

    def persist_callback(self, kind: str, day: date | None, value: Any) -> None:
        """Callback für ``sources``: speichert Wetter, Tageserträge und Leistungsproben."""
        fetched_at = _now()
        with self._connect() as connection:
            if kind == "daily_energy" and day is not None:
                energy = value if isinstance(value, dict) else {}
                connection.execute(
                    """INSERT INTO daily_energy(day, raw_json, epv, fetched_at) VALUES (?, ?, ?, ?)
                       ON CONFLICT(day) DO UPDATE SET raw_json=excluded.raw_json,
                       epv=excluded.epv, fetched_at=excluded.fetched_at""",
                    (day.isoformat(), _json(value), _number(energy.get("epv")), fetched_at),
                )
            elif kind == "power_samples" and day is not None:
                for index, sample in enumerate(value if isinstance(value, list) else []):
                    fields = sample if isinstance(sample, dict) else {}
                    timestamp = fields.get("uploadTime") or f"raw:{fetched_at}:{index}"
                    connection.execute(
                        """INSERT INTO power_samples(day, ts, ppv, cbat, feed_in, raw_json, fetched_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(day, ts) DO UPDATE SET ppv=excluded.ppv, cbat=excluded.cbat,
                           feed_in=excluded.feed_in, raw_json=excluded.raw_json, fetched_at=excluded.fetched_at""",
                        (
                            day.isoformat(),
                            str(timestamp),
                            _number(fields.get("ppv")),
                            _number(fields.get("cbat")),
                            _number(fields.get("feedIn")),
                            _json(sample),
                            fetched_at,
                        ),
                    )
            elif kind == "weather_hourly" and isinstance(value, dict):
                source = str(value.get("source") or "")
                hourly = value.get("payload", {}).get("hourly", {})
                times = hourly.get("time", [])
                for index, timestamp in enumerate(times):
                    try:
                        ts_utc = datetime.fromtimestamp(float(timestamp), timezone.utc).isoformat()
                    except (TypeError, ValueError, OverflowError, OSError):
                        continue

                    def at(name: str) -> float | None:
                        values = hourly.get(name, [])
                        return _number(values[index]) if index < len(values) else None

                    raw_hour = {
                        name: values[index]
                        for name, values in hourly.items()
                        if isinstance(values, list) and index < len(values)
                    }
                    connection.execute(
                        """INSERT INTO weather_hourly(
                                   ts_utc, source, temp_air, wind_speed, ghi, dni, dhi, sunshine_s, fetched_at, raw_json, elevation
                               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(ts_utc, source) DO UPDATE SET
                           temp_air=excluded.temp_air, wind_speed=excluded.wind_speed, ghi=excluded.ghi,
                           dni=excluded.dni, dhi=excluded.dhi, sunshine_s=excluded.sunshine_s,
                               fetched_at=excluded.fetched_at, raw_json=excluded.raw_json,
                               elevation=excluded.elevation""",
                            (
                                ts_utc, source, at("temperature_2m"), at("wind_speed_10m"),
                                at("shortwave_radiation"), at("direct_normal_irradiance"),
                                at("diffuse_radiation"), at("sunshine_duration"), fetched_at, _json(raw_hour),
                                _number(value.get("payload", {}).get("elevation")),
                            ),
                        )

    def upsert_daily_record(self, record: dict) -> None:
        day = record.get("date")
        try:
            date.fromisoformat(day)
        except (TypeError, ValueError):
            return
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO daily(day, raw_json, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(day) DO UPDATE SET raw_json=excluded.raw_json, updated_at=excluded.updated_at""",
                (day, _json(record), _now()),
            )

    def upsert_daily_records(self, records: list[dict]) -> None:
        for record in records:
            if isinstance(record, dict):
                self.upsert_daily_record(record)

    def daily_records(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute("SELECT raw_json FROM daily ORDER BY day").fetchall()
        records = []
        for row in rows:
            try:
                record = json.loads(row["raw_json"])
            except (TypeError, ValueError):
                continue
            if isinstance(record, dict):
                records.append(record)
        return records

    def weather_hours(self, start_utc: str, end_utc: str) -> list[dict]:
        """Liest Wetterstunden im UTC-Zeitfenster ohne pandas-Abhängigkeit."""
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT ts_utc, source, temp_air, wind_speed, ghi, dni, dhi, sunshine_s, elevation
                   FROM weather_hourly
                   WHERE ts_utc >= ? AND ts_utc < ?
                   ORDER BY ts_utc, source""",
                (start_utc, end_utc),
            ).fetchall()
        return [dict(row) for row in rows]


def load_display_records(database_path: Path, legacy_path: Path) -> list[dict]:
    """Liest bevorzugt SQLite; ohne nutzbare Datenbank bleibt daily.json der Rückfallweg."""
    database_path = Path(database_path)
    if database_path.exists():
        try:
            repository = Repository(database_path)
            repository.initialize(legacy_path)
            records = repository.daily_records()
            if records:
                return records
        except (OSError, sqlite3.Error, RuntimeError) as error:
            log.warning("SQLite-Tageshistorie nicht verfügbar; verwende daily.json (%s).", error)
    return storage.load_payload(Path(legacy_path))["records"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
