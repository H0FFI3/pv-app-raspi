 # PV-Tagesbericht

PV-Tagesbericht erfasst und vergleicht tatsächliche Photovoltaik-Erträge mit
modellierten Erträgen. Die App bezieht Anlagendaten über die AlphaESS Open API,
Wetterdaten über Open-Meteo und verwendet pvlib für die PV-Modellierung.

Die Anwendung kann als Server mit Dashboard und Einrichtungsseite oder direkt
zur Erzeugung eines Berichts gestartet werden. Der Server aktualisiert täglich
um 05:30 Uhr den jüngsten abgeschlossenen Tag in der Anlagen-Zeitzone.
Das Modell verwendet die von Open-Meteo gelieferten Stundenintervall-Mittelwerte
und berechnet Wechselrichter-Clipping an diesen Intervallwerten; Randstunden
werden mit dem jeweiligen Intervallmittelpunkt für die Solarposition bewertet.

## Voraussetzungen

- Python 3.14 wird für die derzeitigen Abhängigkeiten empfohlen. `pvlib`
  benötigt unter anderem `h5py`; bei neueren Python-Versionen kann pip mangels
  passendem Wheel versuchen, `h5py` lokal zu kompilieren.
- Node.js und npm werden nur für die optionalen JavaScript-Frontend-Tests
  benötigt.

## Installation

Erstelle im Projektordner eine virtuelle Python-Umgebung und installiere die
Abhängigkeiten.

### Windows (PowerShell)

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Linux oder macOS

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

Python 3.14 wird unter Windows empfohlen, da `pvlib` die native Abhängigkeit
`h5py` benötigt. Auf Raspberry Pi OS kannst du dessen Python 3.11 oder neuer
verwenden. Falls pip `h5py` aus dem Quellcode bauen muss, installiere die
Entwicklungsdateien wie im Raspberry-Pi-Abschnitt beschrieben.

## Konfiguration

Kopiere `.env.example` nach `.env` und trage die Zugangsdaten sowie die
Anlagendaten ein. Die `.env`-Datei enthält vertrauliche Werte und wird nicht
versioniert.

PowerShell:

```powershell
Copy-Item .env.example .env
```

Linux oder macOS:

```bash
cp .env.example .env
```

Die wesentlichen Einstellungen sind:

- AlphaESS-Zugangsdaten: `ALPHAESS_APP_ID` und `ALPHAESS_APP_SECRET`
- Standort: `LATITUDE`, `LONGITUDE` und `TIMEZONE`
- Module, Ausrichtung, Wechselrichter und Systemverluste
- Optionale Dachneigungen je Modulfeld: `TILT_EAST_DEG` und `TILT_WEST_DEG`
- Erster zu erfassender Tag: `DATA_START_DATE`

Weitere optionale Einstellungen, ihre Standardwerte und Hinweise stehen in
`.env.example`. Der Server bietet zusätzlich eine Einrichtungsseite. Werte,
die dort gespeichert werden, liegen in `settings.env` im Datenordner der App;
vorhandene `.env`-Werte haben Vorrang.

Forecast-Tage werden standardmäßig nach 10 Tagen durch vollständige
Archivdaten ersetzt. `WEATHER_UPGRADE_AFTER_DAYS=0` schaltet diese Prüfung aus;
Ist-Ertrag und Stundenmessungen werden bei einer Umstellung beibehalten.
Der optionale öffentliche Lese-Endpunkt `/api/health` verwendet standardmäßig
eine Veraltet-Schwelle von 36 Stunden (`HEALTH_STALE_AFTER_HOURS`).
Qualitätskennzahlen verwenden standardmäßig 80 % Mindestabdeckung und 10 %
Toleranz zwischen unskaliertem Stundenintegral und AlphaESS-Tageswert
(`QUALITY_MIN_COVERAGE`, `QUALITY_EPV_MISMATCH_FRACTION`).
Automatische Wiederholungsversuche erfolgen standardmäßig nach 15 und 60
Minuten; `UPDATE_RETRY_FIRST_MINUTES` und `UPDATE_RETRY_SECOND_MINUTES` passen
diese Abstände an.

Rohdaten und Tageswerte werden im Datenordner zusätzlich in `pv.sqlite`
gespeichert; `daily.json` bleibt als kompatibler Export und Backup erhalten.
Das Dashboard zeigt Modellwechsel, Datenlücken und Qualitätsmarkierungen.
Abdeckung der AlphaESS-Proben wird innerhalb des geschätzten Tageslichtfensters
gemessen. Der öffentliche Lese-Endpunkt `/api/health` enthält nur einen
minimalen Aktualisierungsstatus; schreibende Endpunkte bleiben lokal und
token-geschützt.

## Anwendung starten

### Server mit Dashboard und Einrichtung

Im Projektordner:

```bash
python pv_app.py serve
```

Öffne anschließend <http://127.0.0.1:8765> im Browser. Der Server bindet
standardmäßig nur an `127.0.0.1` und ist damit nur auf dem lokalen Rechner
erreichbar. Der Standard-Port ist `8765`.

Nützliche Server-Optionen:

```bash
python pv_app.py serve --help
python pv_app.py serve --port 9000
python pv_app.py serve --no-browser
python pv_app.py serve --no-schedule
```

### Raspberry Pi im Heimnetz betreiben

Installiere Git, Python mit venv-Unterstützung und die Build-Abhängigkeiten für
Pakete wie `h5py`:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-dev build-essential pkg-config libhdf5-dev
git clone <REPOSITORY-URL> ~/pv-app-raspi
cd ~/pv-app-raspi
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
nano .env
```

Trage die AlphaESS-Zugangsdaten und Anlagenwerte in `.env` ein. Starte den
Server zum Testen mit:

```bash
.venv/bin/python pv_app.py serve --host 0.0.0.0 --no-browser
```

Ermittle die IP-Adresse des Pi (`hostname -I`) und öffne auf einem anderen
Gerät im selben Netzwerk `http://<PI-IP>:8765`. Der Server stellt im Netzwerk
nur den Bericht bereit. Einrichtungsseite und schreibende API-Endpunkte bleiben
auf lokale Zugriffe am Pi beschränkt. Der Bericht ist im Heimnetz ohne Anmeldung
lesbar; gib den Port nicht ins Internet frei und verwende bei Bedarf eine
Firewall-Regel, die nur dein lokales Netz zulässt.

Für den automatischen Start beim Booten ist eine systemd-User-Unit enthalten.
Sie erwartet, dass das Repository `~/pv-app-raspi` heißt und die virtuelle
Umgebung `.venv` darin liegt:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/pv-tagesbericht.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now pv-tagesbericht
sudo loginctl enable-linger "$USER"
```

Passe bei einem anderen Installationspfad `WorkingDirectory` und `ExecStart`
in der Unit-Datei an. Status und Logs:

```bash
systemctl --user status pv-tagesbericht
journalctl --user -u pv-tagesbericht -f
```

Der Zeitplan startet einmal täglich um `UPDATE_TIME` (Standard `05:30`). Dabei
wird der jüngste abgeschlossene Tag erneut von AlphaESS abgerufen; der laufende
Tag wird nicht als unvollständiger Datensatz im Dashboard angezeigt. Der Pi
muss um die geplante Uhrzeit eingeschaltet und mit dem Netzwerk verbunden sein.
Wird der Server erst später an diesem Tag gestartet, holt er den Lauf nach.
Bei jedem automatischen oder manuellen Datenlauf wird außerdem die PVGIS-TMY-
Referenz für das Soll-Ist-Balkendiagramm aktualisiert. Ist PVGIS vorübergehend
nicht erreichbar, läuft die Tagesaktualisierung mit den vorhandenen Daten weiter;
die Referenz wird beim nächsten Lauf erneut abgerufen.
Bei Fehlern versucht der Zeitplan bis zu drei Läufe pro Tag (mit 15 bzw. 60
Minuten Abstand); nach dem dritten Fehlversuch gibt es an diesem Tag keine
weiteren automatischen Versuche.
Die Zeitzone für den Zeitplan ist der Wert von `TIMEZONE`.

### Bericht direkt erzeugen

Ohne das Unterkommando `serve` führt der Einstiegspunkt die Datenerfassung und
Berichterstellung aus:

```bash
python pv_app.py
```

Die verfügbaren Optionen, darunter Offline-Modus und das Überspringen des
Browserstarts, zeigt:

```bash
python pv_app.py --help
```

Gespeicherte Potenziale lassen sich nach einer Modellparameteränderung aus
lokal gespeicherten Wetterstunden neu berechnen, ohne AlphaESS aufzurufen:

```bash
python pv_app.py --recompute
python pv_app.py --recompute --from 2026-01-01 --to 2026-01-31
```

`python tools/calibrate.py` wertet geeignete, nicht abgeregelte Stunden aus und
schlägt einen Wert für `SYSTEM_LOSS_FRACTION` vor. Das Werkzeug ändert keine
Dateien oder Einstellungen.

Mit `python tools/compare_radiation_sources.py --from JJJJ-MM-TT --to JJJJ-MM-TT`
lassen sich Archiv, Forecast und Satellitenstrahlung gegen gespeicherte Iststunden
vergleichen. Die Satellite Radiation API ist regional und je Satellit unterschiedlich
verfügbar; siehe <https://open-meteo.com/en/docs/satellite-radiation-api>. Der
Vergleich ändert die produktive Wetterquelle nicht.

## Tests

### Python-Tests

Installiere die Abhängigkeiten wie oben beschrieben. `pytest` ist in
`requirements.txt` enthalten. Starte dann im Projektordner:

```bash
python -m pytest -q
```

### Optionale Frontend-Tests

Die Tests unter `tests/frontend` verwenden Node.js, npm und jsdom.

```bash
cd tests/frontend
npm install
cd ../..
python -m pytest -q tests/test_frontend.py
```

Wenn Node.js und jsdom installiert sind, führt `python -m pytest -q` außerdem
den Dashboard-Test aus `tests/test_frontend.py` aus. Ohne diese Voraussetzungen
wird dieser Test übersprungen.

## Projektstruktur

```text
.
├── pv_app.py                 Einstiegspunkt: Server oder direkter Berichtslauf
├── pv_config.py              Konfigurationshilfen
├── requirements.txt          Python-Abhängigkeiten
├── .env.example               Vorlage für lokale Konfiguration
├── pvapp/                    Anwendungspaket
│   ├── server.py              HTTP-Server, Dashboard und Einrichtungsseite
│   ├── app.py                 Direkter Daten- und Berichtslauf
│   ├── config.py              Einlesen und Validieren der Konfiguration
│   ├── alphaess_client.py     AlphaESS-API-Zugriff
│   ├── sources.py             Datenquellen und Wetterdaten
│   ├── model.py               PV-Leistungsmodell
│   ├── report.py              HTML-Bericht
│   ├── storage.py             Lokale Datenspeicherung
│   ├── db.py                  SQLite-Datenbank für Tageswerte und Rohdaten
│   ├── updater.py             Aktualisierung und täglicher Zeitplan
│   └── ...                    Anzeige, Einstellungen, Logging und Hilfslogik
├── site/                      Weboberfläche und statische Dateien
│   ├── index.html              Dashboard-Seite
│   ├── dashboard.js            Dashboard-Logik
│   └── styles.css              Darstellung
├── tests/                     Python-Tests und Test-Hilfen
│   └── frontend/               Optionale JavaScript-Tests
├── deploy/                    systemd-Beispiel für den Raspberry Pi
├── tools/                     Entwicklungs- und Diagnosewerkzeuge
├── analyze_pv.py              Optionales PVGIS-Referenzanalyse-Skript
├── compare_daily.py            Optionaler manueller Tagesvergleich
└── alphaess_probe.py          AlphaESS-API-Diagnosewerkzeug
```

Die vom Server verwendeten Daten, Logs und Statusdateien werden im
Anwendungsdatenordner des Benutzers abgelegt, nicht im Quellcodeverzeichnis.
Die Tageshistorie bleibt weiterhin als `daily.json` mit atomarem Schreiben und
Sicherungen erhalten. Zusätzlich speichert `pv.sqlite` Wetterstunden,
AlphaESS-Tagesantworten, 5-Minuten-Leistungsproben und Tagesdatensätze dauerhaft;
eine vorhandene `daily.json` wird beim ersten Start einmalig und ohne Verlust
unbekannter Felder importiert. Rohdaten werden nicht automatisch gelöscht.
Der Speicherbedarf hängt von Anlagenantworten und Abrufhäufigkeit ab; als grobe
Orientierung sind pro Anlage meist einige zehn Kilobyte je erfassten Tag und
damit einige zehn Megabyte pro Jahr einzuplanen.
