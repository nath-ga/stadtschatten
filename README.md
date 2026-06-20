# Stadtschatten

Das Modul berechnet den **Gebäudeschatten zu einer bestimmten Tageszeit** und bestimmt daraus,
welcher Anteil des städtischen Fußwegenetzes zu diesem Zeitpunkt in der Sonne bzw. im Schatten liegt.

Daraus ergeben sich zwei Anwendungen:

- **Schattiger Fußweg:** der schattigste statt des schnellsten Weges zwischen zwei Punkten
  (gewichtetes Routing mit stufenlosem Umschalter).
- **Hitzeexpositions-Layer:** sichtbar machen, *wo entlang realer Laufwege* die Sonnenbelastung
  am höchsten ist – also wo Beschattung (Bäume, Markisen) für Fußgänger am dringendsten gebraucht wird.

Stadtschatten teilt die OpenStreetMap-Datengrundlage mit dem Schwestermodul **Stadtgrün**,
ist aber eigenständig.

---

## Funktionsweise

```
1. Laden        Geh-Graph (osmnx) + Gebäude-Footprints mit Höhe        → modules/loader.py
                Höhe bevorzugt aus LGL-LoD2; OSM als Fallback
2. Schatten     Gebäudeschatten für einen Zeitpunkt (pybdshadow)       → modules/schatten.py
3. Bewertung    Schatten den Wegekanten zuordnen, Sonnenanteil je      → modules/kantenbewertung.py
                Kante, Kantengewichtung
4. Routing      gewichteter kürzester Pfad, schnellster vs. schattigster → modules/routing.py
5. Ausgabe      Folium-Karten (Schatten-Check, Sonnenanteil, Route)
                jeweils mit Lauf-Parametern und Quellenangabe
```

Die Kantenbewertung tastet jede Wegekante in Stützpunkten ab und prüft mit *einem*
räumlichen Verschnitt gegen die vereinigte Schattenfläche, welcher Anteil jeder Kante
beschattet ist. Ergebnis pro Kante: `sonnenanteil` (0 = ganz im Schatten, 1 = volle Sonne)
sowie zwei Gewichte fürs Routing.

---

## Gebäudehöhen (Kern von v2)

Verlässliche Höhen sind die Voraussetzung für belastbare Schattenwerte. Die Höhe wird in
`modules/loader.py` als Fallback-Kette bestimmt:

```
1. LGL-LoD2 (amtlich, gemessen)   ← bevorzugt, innerhalb Baden-Württembergs
2. OSM height
3. OSM building:levels × 3 m
4. Default 6 m (2 Geschosse)
```

Liegen für das Suchgebiet LGL-LoD2-Kacheln vor, werden deren amtliche Footprints und
`measuredHeight` direkt verwendet (Modul `modules/lgl_lod2.py`); andernfalls greift der
OSM-Weg. Die LGL-Kacheln werden als CityGML-Dateien (`LoD2_*.gml`) im Ordner `data/`
erwartet und auf das aktuelle Suchgebiet zugeschnitten.

**Verifiziert am Testgebiet Esslingen (vier 1-km-Kacheln, 3.885 Gebäude):**
100 % Höhenabdeckung. Etwa 81 % tragen die Höhe am Gebäude selbst, die übrigen ~19 % auf
ihren Gebäudeteilen (`BuildingPart`) – beide werden ausgelesen. Zum Vergleich: über OSM
allein lagen für dasselbe Gebiet nur ~13–32 % echte Höhen vor, der Rest war geschätzt.

**Wichtige Einordnung:** `measuredHeight` ist die Höhe bis zum höchsten Punkt (Firsthöhe).
pybdshadow extrudiert flach bis dahin, wodurch der Schatten bei Steildächern leicht
überschätzt wird. Für die *relative* Routenwahl (schattig vs. sonnig) hebt sich das
weitgehend auf; nur der absolute Sonnenanteil ist minimal überschätzt.

---

## Installation & Nutzung

```bash
# eigene Umgebung (empfohlen – getrennt von anderen Modulen)
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # Windows PowerShell
# source .venv/bin/activate          # Linux/macOS
pip install -r requirements.txt

# kompletter Durchlauf
python run.py
```

Ergebnisse landen als HTML-Karten im Ordner `output/`. Einzelne Module lassen sich
auch separat starten (z. B. `python modules/schatten.py`).

### Konfiguration (`config.py`)

| Parameter | Bedeutung |
|---|---|
| `PLACE` | Ort (ganzer Ort), OSM-kompatibel |
| `ZENTRUM`, `RADIUS_M` | optionaler Zuschnitt auf einen Kreis (schnell, zum Entwickeln); `ZENTRUM = None` → ganzer `PLACE`. Bestimmt zugleich, welche LGL-Kacheln verwendet werden. |
| `DATUM`, `UHRZEIT`, `ZEITZONE` | Zeitpunkt des Schattenwurfs |
| `START`, `ZIEL` | Routing-Punkte als `(lat, lon)`; `None` → automatische Demo-Diagonale (Süd­west- nach Nordost-Ecke des Gebiets) |
| `ALPHA_SCHATTIG` | Stärke der Schattenbevorzugung (siehe unten) |

LGL-LoD2-Kacheln liegen als `LoD2_*.gml` im Ordner `data/`.

### Der `ALPHA`-Regler

Die Kantengewichtung lautet:

```
gewicht = laenge * (1 + ALPHA * sonnenanteil)
```

`ALPHA` ist der **Wechselkurs zwischen Umweg und Sonne**: wie viele zusätzliche Meter
in Kauf genommen werden, um einen Meter Sonne zu vermeiden.

- `ALPHA = 0` → schnellster Weg (Schatten egal)
- `ALPHA = 3` → ein Sonnenmeter „kostet" wie 4 Meter Gehen
- höher → stärkere Schattenbevorzugung, größere Umwege

Wichtig: `ALPHA` wirkt nur, wo es schattige Alternativen *gibt*. Über offene Plätze,
Brücken oder freie Geraden existiert kein Schatten – diese Abschnitte bleiben sonnig,
unabhängig von `ALPHA`. Jenseits des Punktes einer Strecke an dem der schattige
Umweg billiger wird als die sonnige Direktroute, ändert ein höheres `ALPHA` nichts mehr.

---

## Datengrundlage & Technik

| Zweck | Quelle / Werkzeug |
|---|---|
| Wegenetz, Gebäude-Footprints (Fallback) | OpenStreetMap via `osmnx` |
| Gebäudehöhen | **LGL-LoD2** (`measuredHeight`, amtlich) innerhalb BW · **Fallback:** OSM (`height`, `building:levels`, Default 2 Geschosse) |
| Schatten / Sonnenstand | `pybdshadow` |
| CityGML einlesen | eigener Parser `modules/lgl_lod2.py` (ElementTree + `shapely`) |
| Geometrie | `geopandas`, `shapely` |
| Graph / Routing | `networkx` |
| Karten | `folium` |

**Koordinatensystem:** EPSG:25832 (ETRS89/UTM32N) für alle metrischen Berechnungen –
identisch mit dem CRS der LGL-Daten, daher kein Umprojizieren der Höhendaten nötig.

---

## Stand (v2)

| Schritt | Status |
|---|---|
| pybdshadow verifiziert | ✅ |
| Loader: Geh-Graph + Gebäude mit Höhe | ✅ |
| Schatten-Wrapper (pybdshadow) | ✅ |
| Schatten-zu-Kante-Zuordnung + Kantengewichtung | ✅ |
| Routing: schnellster vs. schattigster Weg (Umschalter) | ✅ |
| Folium-Kartenausgabe mit Parametern + Quellenangabe | ✅ |
| Einstiegspunkt `run.py` | ✅ |
| **Echte Gebäudehöhen via LGL-LoD2 (ersetzt OSM-Schätzung in BW)** | ✅ |
| Feste `START`/`ZIEL` für stabile Vergleiche | ⬜ optional |
| Kachel-Auswahl je Gebiet + Höhen-Cache (Skalierung über Esslingen hinaus) | ⬜ offen |
| GPX-Export | ⬜ optional, offen |

---

## Validierung

Schattenrichtung und -länge werden gegen den berechneten Sonnenstand geprüft: Beispiel
Esslingen am Neckar, 21.06., Sonne im SSW bei hoher Sonnenhöhe → Schatten zeigen nach NNO;
Schattenlänge konsistent zur Gebäudehöhe und zum physikalischen Sonnenstand.

Geprüft an zwei Orten (Esslingen, Denkendorf). Mit der LGL-LoD2-Anbindung beruhen die
Höhen im Testgebiet Esslingen zu 100 % auf amtlichen Messwerten (Median ~11 m) statt auf
Schätzung – die absoluten Schattenwerte sind damit erstmals belastbar.

---

## Grenzen dieser Auswertung

Bewusste, dokumentierte Einschränkungen:

1. **Wege = Straßenachsen, nicht Bürgersteige.** Der osmnx-`walk`-Graph nutzt die
   Straßenachse, wo Gehwege nicht als eigene Geometrie kartiert sind. Fußgänger laufen
   am Gebäuderand (schattiger) statt in der Straßenmitte. Der Fußgänger-Schatten wird
   dadurch eher **unter- als überschätzt**.
2. **Höhen nur in Baden-Württemberg amtlich.** Innerhalb BW (und wo Kacheln vorliegen)
   kommen gemessene LGL-LoD2-Höhen zum Einsatz. Außerhalb BW oder ohne Kachel greift die
   OSM-Schätzung – dort bleiben die absoluten Werte vorläufig. `measuredHeight` ist
   Firsthöhe (siehe Abschnitt *Gebäudehöhen*).
3. **Ein Zeitpunkt.** Der Schatten gilt nur für den eingestellten Moment.
4. **Nur Gebäudeschatten.** Baumschatten und Vegetation sind nicht enthalten
   (späterer Ausbau über nDOM).
5. **Keine thermische Strahlungsmodellierung.** Bewusste Abgrenzung zu wissenschaftlich
   rigorosen Werkzeugen wie UMEP/SOLWEIG.

---

## Ausblick

- **Frequenz × Sonnenbelastung:** Stark begangene *und* stark besonnte Wege als
  Prioritätskarte für Beschattungsmaßnahmen – der eigentliche planerische Hebel. Ansätze:
  Betweenness-Zentralität (strukturell) oder zielorientiertes Routing (zu Schulen,
  Bahnhof, Busbahnhof). Bleibt ein Modell, keine gemessene Frequenz.
- **Kachel-Auswahl je Gebiet + Höhen-Cache:** damit über Esslingen hinaus skalierbar und
  ohne wiederholtes Parsen der großen CityGML-Kacheln.
- **GPX-Export** der gewählten Route (für Navigation unterwegs).
- **Schattenseiten-Sampling:** Stützpunkte seitlich von der Achse versetzen und die
  schattigere Straßenseite werten – bildet reales Fußgängerverhalten ab.
- **Baumschatten** über nDOM.
- Weitere Städte.

---

## Datenlizenz

OpenStreetMap-Daten © OpenStreetMap-Mitwirkende (ODbL).

Diese Auswertung nutzt amtliche 3D-Gebäudemodelle (LoD2) des Landesamts für Geoinformation
und Landentwicklung Baden-Württemberg. Datenlizenz Deutschland – Namensnennung 2.0,
Quellenangabe: **„Datenquelle: LGL, www.lgl-bw.de"**. Die Angabe erscheint in der README
sowie auf jeder erzeugten Karte.