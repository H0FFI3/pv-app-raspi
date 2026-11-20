"""Schlägt einen Systemverlust-Anteil aus nicht abgeregelten Ist-/Modellstunden vor."""

from __future__ import annotations

import argparse
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pvapp import paths, storage
from pvapp.config import load_config
from pvapp.display import build_display_records


def suggest_system_loss(
    records: list[dict],
    current_loss: float,
    min_potential_kwh: float = 0.3,
) -> tuple[float | None, int]:
    """Gibt einen robusten Vorschlag und die Zahl ausgewerteter Stunden zurück."""
    ratios = []
    for record in records:
        for point in record.get("hourly", []):
            actual, potential = point.get("actual_kwh"), point.get("potential_kwh")
            if point.get("curtailed") or actual is None or potential is None:
                continue
            try:
                actual, potential = float(actual), float(potential)
            except (TypeError, ValueError):
                continue
            if math.isfinite(actual) and math.isfinite(potential) and potential >= min_potential_kwh:
                ratios.append(actual / potential)
    if not ratios:
        return None, 0
    ratio = statistics.median(ratios)
    return max(0.0, min(0.99, 1 - (1 - current_loss) * ratio)), len(ratios)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Schlägt SYSTEM_LOSS_FRACTION vor, ändert die Konfiguration aber nicht.")
    parser.add_argument("--min-potential-kwh", type=float, default=0.3, help="Mindestpotenzial je Stunde (Standard: 0,3 kWh).")
    options = parser.parse_args(argv)
    config = load_config()
    payload = storage.load_payload(paths.data_path())
    records = build_display_records(payload["records"], config)
    proposal, count = suggest_system_loss(records, config.system_loss_fraction, options.min_potential_kwh)
    if proposal is None:
        print("Zu wenige geeignete nicht abgeregelte Stunden für einen Vorschlag.")
        return 1
    print(f"Ausgewertete Stunden: {count}")
    print(f"Aktueller Wert SYSTEM_LOSS_FRACTION: {config.system_loss_fraction:.4f}")
    print(f"Vorschlag SYSTEM_LOSS_FRACTION: {proposal:.4f} (wird nicht gespeichert)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
