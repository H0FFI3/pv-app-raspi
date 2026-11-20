"""Erzeugt die PVGIS-TMY-Referenz im App-Datenordner."""

import sys

from pvapp.config import ConfigError, load_config
from pvapp.paths import tmy_cache_path
from pvapp.reference import refresh_tmy_reference


def main() -> None:
    config = load_config()
    reference = refresh_tmy_reference(config, tmy_cache_path())
    print(f"Installierte DC-Leistung: {config.installed_kwp:.2f} kWp")
    print(f"Geschätzte jährliche AC-Energie nach dem PV-Modell: {reference['annual_kwh']:.0f} kWh")
    print(f"TMY-Referenz gespeichert: {tmy_cache_path()}")
    print("Grundlage: PVGIS-TMY, aktuelle Modellparameter und Wechselrichterbegrenzung.")


if __name__ == "__main__":
    try:
        main()
    except ConfigError as error:
        sys.exit(str(error))
