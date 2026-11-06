 # PV-Tagesbericht

PV-Tagesbericht erfasst und vergleicht tatsächliche Photovoltaik-Erträge mit
modellierten Erträgen. Die App bezieht Anlagendaten über die AlphaESS Open API,
Wetterdaten über Open-Meteo und verwendet pvlib für die PV-Modellierung.

Die Anwendung kann als Server mit Dashboard und Einrichtungsseite oder direkt
zur Erzeugung eines Berichts gestartet werden. Der Server kann Daten außerdem
automatisch täglich aktualisieren.

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
python3.14 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

Falls Python 3.14 nicht installiert ist, installiere es zuerst oder verwende
eine Python-Version, für die alle Projektabhängigkeiten passende Pakete
anbieten.

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
- Erster zu erfassender Tag: `DATA_START_DATE`

Weitere optionale Einstellungen, ihre Standardwerte und Hinweise stehen in
`.env.example`. Der Server bietet zusätzlich eine Einrichtungsseite. Werte,
die dort gespeichert werden, liegen in `settings.env` im Datenordner der App;
vorhandene `.env`-Werte haben Vorrang.

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
npm test
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
│   ├── updater.py             Aktualisierung und täglicher Zeitplan
│   └── ...                    Anzeige, Einstellungen, Logging und Hilfslogik
├── site/                      Weboberfläche und statische Dateien
│   ├── index.html              Dashboard-Seite
│   ├── dashboard.js            Dashboard-Logik
│   └── styles.css              Darstellung
├── tests/                     Python-Tests und Test-Hilfen
│   └── frontend/               Optionale JavaScript-Tests
├── tools/                     Entwicklungs- und Diagnosewerkzeuge
├── analyze_pv.py              Optionales PVGIS-Referenzanalyse-Skript
├── compare_daily.py            Optionaler manueller Tagesvergleich
└── alphaess_probe.py          AlphaESS-API-Diagnosewerkzeug
```

Die vom Server verwendeten Daten, Logs und Statusdateien werden im
Anwendungsdatenordner des Benutzers abgelegt, nicht im Quellcodeverzeichnis.
