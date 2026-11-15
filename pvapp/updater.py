"""Aktualisierung als eigener Prozess, Status-Datei und Zeitplan für den Serve-Modus.

Die Aktualisierung läuft als Kindprozess (``python pv_app.py --no-open``): Der Server bleibt klein
(kein pandas/pvlib im Speicher), ein Absturz der Berechnung reißt ihn nicht mit, und der Speicher wird
nach jedem Lauf wieder frei. Leichtgewichtig: importiert weder pandas noch pvlib.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable

from . import paths

log = logging.getLogger(__name__)

LOG_TAIL_LINES = 40


class StatusStore:
    """Kleine JSON-Datei mit dem Zustand der letzten Aktualisierungen (übersteht Neustarts)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or paths.status_path()
        self._lock = threading.Lock()

    def read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def update(self, **changes) -> dict:
        with self._lock:
            data = {**self.read(), **changes}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name + ".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, self.path)
            return data


def update_command() -> list[str]:
    """Aktualisiert den jüngsten abgeschlossenen Tag erneut."""
    if paths.is_frozen():
        return [sys.executable, "--no-open", "--no-report", "--refresh-days", "1"]
    return [
        sys.executable,
        str(paths.project_root() / "pv_app.py"),
        "--no-open",
        "--no-report",
        "--refresh-days",
        "1",
    ]


def last_update_log_path() -> Path:
    return paths.log_directory() / "last-update.log"


def last_update_output_path() -> Path:
    """Rohausgabe (stdout/stderr) des Kindprozesses: hilft bei Abstürzen noch vor dem Logging."""
    return paths.log_directory() / "last-update.out"


def read_log_tail(path: Path | None = None, lines: int = LOG_TAIL_LINES) -> list[str]:
    path = path or last_update_log_path()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [line for line in text.splitlines() if line.strip()][-lines:]


def _headline(tail: list[str]) -> str:
    """Aussagekräftigste Zeile für die Anzeige: letzte Fehler-/Warnzeile, sonst die letzte Zeile."""
    line = ""
    for candidate in reversed(tail):
        if any(marker in candidate for marker in ("fehlgeschlagen", "Fehler", "nicht möglich", "Übersprungen")):
            line = candidate
            break
    else:
        line = tail[-1] if tail else ""
    return line if len(line) <= 220 else line[:217] + "..."


class Updater:
    """Startet höchstens eine Aktualisierung gleichzeitig und hält den Status aktuell."""

    def __init__(
        self,
        status: StatusStore,
        *,
        command: Callable[[], list[str]] = update_command,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        now: Callable[[], datetime] | None = None,
        log_path: Callable[[], Path] = last_update_log_path,
        output_path: Callable[[], Path] | None = None,
    ) -> None:
        self.status = status
        self._command = command
        self._popen = popen
        self._now = now or (lambda: datetime.now().astimezone())
        self._log_path = log_path
        self._output_path = output_path or (lambda: self._log_path().with_suffix(".out"))
        self._process: subprocess.Popen | None = None
        self._log_handle = None
        self._trigger = ""
        self._lock = threading.Lock()

    def running(self) -> bool:
        with self._lock:
            return self._running_locked()

    def _running_locked(self) -> bool:
        if self._process is None:
            return False
        code = self._process.poll()
        if code is None:
            return True
        self._finish(code)
        return False

    def poll(self) -> None:
        self.running()

    def start(self, trigger: str) -> bool:
        """Startet eine Aktualisierung. ``False``, wenn schon eine läuft oder der Start scheitert."""
        with self._lock:
            if self._running_locked():
                return False
            now = self._now()
            log_file = self._log_path()
            try:
                log_file.parent.mkdir(parents=True, exist_ok=True)
                self._log_handle = open(self._output_path(), "wb")
                options = {}
                if os.name == "nt":
                    options["creationflags"] = subprocess.CREATE_NO_WINDOW
                self._process = self._popen(
                    [*self._command(), "--log-file", str(log_file)],
                    stdin=subprocess.DEVNULL,
                    stdout=self._log_handle,
                    stderr=subprocess.STDOUT,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
                    **options,
                )
            except OSError as error:
                log.error("Aktualisierung konnte nicht gestartet werden: %s", error)
                today = now.date().isoformat()
                previous = self.status.read()
                attempts = previous.get("attempts", 0) if previous.get("attempts_date") == today else 0
                self.status.update(
                    last_started=now.isoformat(timespec="seconds"),
                    last_finished=now.isoformat(timespec="seconds"),
                    last_ok=False,
                    last_trigger=trigger,
                    last_message=f"Start nicht möglich: {error}",
                    attempts_date=today,
                    attempts=attempts + 1,
                )
                self._close_log()
                return False
            self._trigger = trigger
            today = now.date().isoformat()
            previous = self.status.read()
            attempts = previous.get("attempts", 0) if previous.get("attempts_date") == today else 0
            self.status.update(
                last_started=now.isoformat(timespec="seconds"),
                last_trigger=trigger,
                last_ok=None,
                last_message="Aktualisierung läuft …",
                attempts_date=today,
                attempts=attempts + 1,
            )
            log.info("Aktualisierung gestartet (%s).", trigger)
            return True

    def _finish(self, code: int) -> None:
        self._process = None
        self._close_log()
        now = self._now()
        tail = read_log_tail(self._log_path()) or read_log_tail(self._output_path())
        previous = self.status.read()
        ok = code == 0
        changes = {
            "last_finished": now.isoformat(timespec="seconds"),
            "last_ok": ok,
            "last_message": "Aktualisierung abgeschlossen." if ok else (_headline(tail) or f"Abbruch mit Code {code}"),
        }
        if ok:
            changes["last_success_date"] = now.date().isoformat()
            changes["last_success_at"] = now.isoformat(timespec="seconds")
        self.status.update(**changes)
        run = {
            "started_at": previous.get("last_started"),
            "finished_at": now.isoformat(timespec="seconds"),
            "duration_seconds": _run_duration(previous.get("last_started"), now),
            "trigger": self._trigger,
            "ok": ok,
            "exit_code": code,
        }
        summary = _read_last_run_summary(previous.get("last_started"))
        for key in (
            "days_ok",
            "days_skipped_older",
            "skipped_days",
            "signals_updated",
            "weather_upgrades",
            "data_api_calls",
            "error_classes",
        ):
            if key in summary:
                run[key] = summary[key]
        self._append_run(
            run
        )
        log.info("Aktualisierung beendet: %s", "erfolgreich" if ok else f"Fehler (Code {code})")

    def _append_run(self, run: dict) -> None:
        path = self.status.path.with_name("runs.jsonl")
        try:
            rows = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
            rows.append(json.dumps(run, ensure_ascii=False, separators=(",", ":")))
            rows = rows[-200:]
            path.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as stream:
                    stream.write("\n".join(rows) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            except BaseException:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
                raise
        except OSError as error:
            log.warning("Laufhistorie konnte nicht gespeichert werden: %s", error)

    def _close_log(self) -> None:
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except OSError:
                pass
            self._log_handle = None

    def stop(self) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
            self._close_log()


def due(
    now: datetime,
    start_time: time,
    status: dict,
    backoff_minutes: tuple[int, int] = (15, 60),
) -> bool:
    """Soll heute ein Lauf starten? Fehler werden höchstens dreimal mit Backoff wiederholt."""
    if now.time().replace(tzinfo=None) < start_time:
        return False

    today = now.date().isoformat()
    if status.get("last_success_date") == today:
        return False
    attempts = status.get("attempts", 0) if status.get("attempts_date") == today else 0
    if attempts >= 3:
        return False
    started = status.get("last_started")
    if started:
        try:
            last_started = datetime.fromisoformat(started)
        except ValueError:
            return True
        if last_started.date() == now.date() and status.get("last_ok") is not False:
            return False
    if attempts:
        finished = status.get("last_finished")
        if not finished:
            return False
        try:
            last_finished = datetime.fromisoformat(finished)
        except ValueError:
            return False
        if now.tzinfo is None and last_finished.tzinfo is not None:
            last_finished = last_finished.replace(tzinfo=None)
        elif now.tzinfo is not None and last_finished.tzinfo is None:
            last_finished = last_finished.replace(tzinfo=now.tzinfo)
        backoff = backoff_minutes[min(attempts - 1, 1)]
        if now < last_finished + timedelta(minutes=backoff):
            return False
    return True


def _run_duration(started: str | None, finished: datetime) -> float | None:
    if not started:
        return None
    try:
        start = datetime.fromisoformat(started)
    except ValueError:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=timezone.utc)
    return max(0.0, (finished - start).total_seconds())


def _read_last_run_summary(expected_started: str | None = None) -> dict:
    try:
        value = json.loads(paths.last_run_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        log.warning("Laufzusammenfassung ist nicht lesbar (%s).", error)
        return {}
    if not isinstance(value, dict) or not expected_started or not value.get("started_at"):
        return {}
    try:
        expected = datetime.fromisoformat(expected_started)
        actual = datetime.fromisoformat(value["started_at"])
        if expected.tzinfo is None:
            expected = expected.replace(tzinfo=timezone.utc)
        if actual.tzinfo is None:
            actual = actual.replace(tzinfo=timezone.utc)
        if abs((actual - expected).total_seconds()) > 300:
            return {}
    except (TypeError, ValueError):
        return {}
    return value


def recent_runs(path: Path, limit: int = 20) -> list[dict]:
    """Liest sichere, für das Dashboard geeignete Felder aus der Laufhistorie."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    except FileNotFoundError:
        return []
    except OSError as error:
        log.warning("Laufhistorie konnte nicht gelesen werden: %s", error)
        return []
    runs = []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            log.warning("Ungültiger Eintrag in der Laufhistorie wird übersprungen.")
            continue
        if not isinstance(item, dict):
            continue
        skipped = item.get("skipped_days")
        skipped_count = len(skipped) if isinstance(skipped, list) else 0
        try:
            skipped_count += max(0, int(item.get("days_skipped_older", 0)))
        except (TypeError, ValueError):
            pass
        runs.append({
            "started_at": item.get("started_at"),
            "finished_at": item.get("finished_at"),
            "duration_seconds": item.get("duration_seconds"),
            "days_ok": item.get("days_ok", 0),
            "days_skipped": skipped_count,
            "ok": bool(item.get("ok")),
        })
    return list(reversed(runs))
    try:
        start = datetime.fromisoformat(started)
        if start.tzinfo is None and finished.tzinfo is not None:
            start = start.replace(tzinfo=finished.tzinfo)
        elif finished.tzinfo is None and start.tzinfo is not None:
            start = start.replace(tzinfo=None)
        return max(0.0, (finished - start).total_seconds())
    except ValueError:
        return None


def describe_status(status: dict, running: bool) -> dict:
    """Anzeige für den Berichtskopf: Text und Zustand."""
    if running:
        return {"running": True, "ok": None, "text": "Aktualisierung läuft …"}
    finished = status.get("last_finished")
    if not finished:
        return {"running": False, "ok": None, "text": "Noch keine Aktualisierung."}
    try:
        when = datetime.fromisoformat(finished).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        when = finished
    if status.get("last_ok"):
        return {"running": False, "ok": True, "text": f"Zuletzt aktualisiert: {when}"}
    return {"running": False, "ok": False, "text": f"Letzte Aktualisierung fehlgeschlagen ({when}): {status.get('last_message', '')}"}


def next_slot_text(now: datetime, update_time: time, status: dict) -> str:
    today = now.date().isoformat()
    started = status.get("last_started", "")
    try:
        started_today = datetime.fromisoformat(started).date().isoformat() == today
    except ValueError:
        started_today = False
    done_today = started_today or status.get("last_success_date") == today
    if not done_today and now.time().replace(tzinfo=None) >= update_time:
        return "Nächste Aktualisierung: sobald möglich"
    run_date = now.date() + timedelta(days=1) if done_today else now.date()
    next_run = datetime.combine(run_date, update_time, tzinfo=now.tzinfo)
    return f"Nächste Aktualisierung: {next_run.strftime('%d.%m. um %H:%M')}"


class Scheduler(threading.Thread):
    """Prüft regelmäßig, ob eine geplante Aktualisierung fällig ist. Lädt die Konfiguration nur neu,
    wenn sich Einstellungsdateien geändert haben (kein Log-Spam, keine unnötige Arbeit)."""

    def __init__(
        self,
        updater: Updater,
        get_settings: Callable[[], tuple],
        *,
        interval_seconds: float = 30.0,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(daemon=True, name="pv-scheduler")
        self.updater = updater
        self._get_settings = get_settings
        self._interval = interval_seconds
        self._now = now
        self._stop_event = threading.Event()

    def tick(self) -> bool:
        """Ein Prüfschritt (für Tests öffentlich). ``True``, wenn eine Aktualisierung gestartet wurde."""
        self.updater.poll()
        settings = self._get_settings()
        configured, update_time, timezone = settings[:3]
        backoff = settings[3] if len(settings) > 3 else (15, 60)
        if not configured or self.updater.running():
            return False
        if self._now is not None:
            now = self._now()
        elif timezone:
            from zoneinfo import ZoneInfo

            now = datetime.now(ZoneInfo(timezone))
        else:
            now = datetime.now().astimezone()
        if due(now, update_time, self.updater.status.read(), backoff):
            return self.updater.start("schedule")
        return False

    def run(self) -> None:
        while not self._stop_event.wait(self._interval):
            try:
                self.tick()
            except Exception:  # der Zeitplan darf den Server nie beenden
                log.exception("Fehler im Zeitplan")

    def stop(self) -> None:
        self._stop_event.set()
