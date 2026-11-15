import json
import sqlite3
from datetime import date, datetime, timezone

from pvapp import db


def test_schema_is_migrated_to_current_version(tmp_path):
    path = tmp_path / "pv.sqlite"
    repository = db.Repository(path)

    repository.initialize()
    repository.initialize()

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"daily", "daily_energy", "power_samples", "weather_hourly", "legacy_payload", "migration_state"} <= tables


def test_daily_json_is_imported_once_without_losing_unknown_fields(tmp_path):
    legacy = tmp_path / "daily.json"
    record = {
        "date": "2026-10-13",
        "actual_kwh": 3.2,
        "potential_kwh": 4.1,
        "sunshine_hours": 2.5,
        "future_field": {"source": "legacy", "value": 7},
    }
    payload = {"records": [record, {"old_invalid": True}], "custom_root_field": ["keep", 1]}
    legacy.write_text(json.dumps(payload), encoding="utf-8")
    repository = db.Repository(tmp_path / "pv.sqlite")

    repository.initialize(legacy)
    repository.upsert_daily_record({**record, "actual_kwh": 8})
    repository.initialize(legacy)

    assert repository.daily_records() == [{**record, "actual_kwh": 8}]
    with sqlite3.connect(repository.path) as connection:
        imported = json.loads(connection.execute("SELECT raw_json FROM legacy_payload").fetchone()[0])
    assert imported == payload
    assert json.loads(legacy.read_text(encoding="utf-8")) == payload


def test_daily_upsert_replaces_existing_record_and_keeps_arbitrary_fields(tmp_path):
    repository = db.Repository(tmp_path / "pv.sqlite")
    repository.initialize()
    repository.upsert_daily_record({"date": "2026-10-13", "extra": "first"})
    repository.upsert_daily_record({"date": "2026-10-13", "extra": "second", "nested": [1, 2]})

    assert repository.daily_records() == [
        {"date": "2026-10-13", "extra": "second", "nested": [1, 2]}
    ]


def test_display_loading_prefers_database_and_falls_back_to_daily_json(tmp_path):
    legacy = tmp_path / "daily.json"
    original = {"records": [{"date": "2026-10-13", "actual_kwh": 1}]}
    legacy.write_text(json.dumps(original), encoding="utf-8")
    database = tmp_path / "pv.sqlite"

    assert db.load_display_records(database, legacy) == original["records"]
    repository = db.Repository(database)
    repository.initialize(legacy)
    replacement = {"date": "2026-10-13", "actual_kwh": 9, "new_field": True}
    repository.upsert_daily_record(replacement)

    assert db.load_display_records(database, legacy) == [replacement]


def test_raw_data_callback_upserts_weather_and_alphaess_samples(tmp_path):
    repository = db.Repository(tmp_path / "pv.sqlite")
    repository.initialize()
    day = date(2026, 10, 13)
    stamp = int(datetime(2026, 10, 13, tzinfo=timezone.utc).timestamp())

    repository.persist_callback(
        "weather_hourly",
        None,
        {
            "source": "archive",
            "payload": {
                "elevation": 245,
                "hourly": {
                    "time": [stamp],
                    "temperature_2m": [15],
                    "wind_speed_10m": [2],
                    "shortwave_radiation": [100],
                    "direct_normal_irradiance": [80],
                    "diffuse_radiation": [20],
                    "sunshine_duration": [300],
                },
            },
        },
    )
    repository.persist_callback("daily_energy", day, {"epv": 2.7, "unknown": "kept"})
    sample = {"uploadTime": "2026-10-13 12:00:00", "ppv": 1234, "cbat": 95, "feedIn": -50, "extra": "kept"}
    repository.persist_callback("power_samples", day, [sample])
    repository.persist_callback("power_samples", day, [{**sample, "ppv": 1400}])

    with sqlite3.connect(repository.path) as connection:
        weather = connection.execute("SELECT ghi, raw_json, elevation FROM weather_hourly").fetchone()
        energy = json.loads(connection.execute("SELECT raw_json FROM daily_energy").fetchone()[0])
        samples = connection.execute(
            "SELECT ppv, cbat, feed_in, raw_json FROM power_samples"
        ).fetchone()
    assert energy == {"epv": 2.7, "unknown": "kept"}
    assert weather[0] == 100 and json.loads(weather[1])["temperature_2m"] == 15
    assert weather[2] == 245
    assert tuple(samples[:3]) == (1400, 95, -50)
    assert json.loads(samples[3])["extra"] == "kept"
